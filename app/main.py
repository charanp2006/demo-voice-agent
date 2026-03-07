"""
SmileCare Dental Clinic – FastAPI application with real-time WebSocket voice conversation.

WebSocket protocol
──────────────────
Client → Server:
  { "type": "start_conversation" }
  (binary)  audio_chunk  (PCM-16 LE, 16 kHz, mono)
  { "type": "end_of_speech" }
  { "type": "stop_conversation" }

Server → Client:
  { "type": "conversation_started", "session_id": "..." }
  { "type": "partial_transcript", "text": "..." }
  { "type": "final_transcript",   "text": "..." }
  { "type": "assistant_stream",    "text": "..." }
  { "type": "assistant_done" }
  { "type": "error", "message": "..." }
"""

import asyncio
import base64
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import (
    chat_messages_collection,
    conversations_collection,
    seed_initial_data,
)
from app.models.schema import ChatRequest
from app.routers import clinic
from app.routers import vapi_webhook
from app.services.agent_service import process_message, process_message_stream
from app.services.voice_service import (
    pcm_to_wav,
    text_to_speech_bytes_async,
    transcribe_audio_bytes_async,
)

# ── App init ─────────────────────────────────────────────────

app = FastAPI(title="SmileCare Dental Clinic", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR.parent / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

app.include_router(clinic.router)
app.include_router(vapi_webhook.router)


# ── Startup event ────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    seed_initial_data()


# ── REST endpoints ───────────────────────────────────────────

@app.get("/history")
def get_history(session_id: str = None, limit: int = 50):
    safe_limit = max(1, min(limit, 200))
    query = {}
    if session_id:
        query["session_id"] = session_id
    messages = list(
        chat_messages_collection.find(query).sort("created_at", -1).limit(safe_limit)
    )
    messages.reverse()
    for m in messages:
        m["_id"] = str(m["_id"])
        if isinstance(m.get("created_at"), datetime):
            m["created_at"] = m["created_at"].isoformat()
    return {"messages": messages}


@app.post("/chat")
def chat(request: ChatRequest):
    """Simple text chat (non-streaming, for testing)."""
    reply = process_message(request.message)
    now = datetime.now(timezone.utc)
    chat_messages_collection.insert_many([
        {"role": "user", "content": request.message, "message_type": "text", "created_at": now},
        {"role": "assistant", "content": reply, "message_type": "text", "created_at": now},
    ])
    return {"response": reply}


# ── WebSocket – real-time voice conversation ─────────────────

PARTIAL_TRANSCRIPTION_INTERVAL = 2.0   # seconds between interim STT calls
SAMPLE_RATE = 16000                     # expected PCM sample rate from client

# ── Server-side transcript filtering (second line of defense) ─
_HALLUCINATION_RE = [
    re.compile(r"^thank(?:s| you)\s*(?:for)?\s*(?:watching|listening|viewing)", re.I),
    re.compile(r"^(?:please\s+)?(?:like|subscribe)", re.I),
    re.compile(r"^\s*you\s*$", re.I),
    re.compile(r"^(?:um+|uh+|hmm+|ah+|oh+)\s*\.?\s*$", re.I),
    re.compile(r"^\[.*\]$"),               # [Music], [Applause]
    re.compile(r"^\(.*\)$"),               # (upbeat music)
    re.compile(r"^\s*\.+\s*$"),            # just dots / ellipsis
    re.compile(r"^bye[\s.!]*$", re.I),
]
_MIN_TRANSCRIPT_WORDS = 2
_MIN_TRANSCRIPT_CHARS = 4


def _is_valid_transcript(text: str) -> bool:
    """Return False for hallucinations, noise artefacts, and very short text."""
    if not text:
        return False
    if len(text) < _MIN_TRANSCRIPT_CHARS:
        return False
    if len(text.split()) < _MIN_TRANSCRIPT_WORDS:
        return False
    for pat in _HALLUCINATION_RE:
        if pat.search(text):
            print(f"[stt-filter] rejected hallucination: {text!r}")
            return False
    return True


@app.websocket("/ws/voice")
async def websocket_voice(ws: WebSocket):
    await ws.accept()

    session_id: str | None = None
    audio_buffer = bytearray()
    conversation_history: list[dict] = []
    partial_task: asyncio.Task | None = None
    last_partial_time: float = 0.0
    is_active = False

    async def _send(payload: dict):
        try:
            await ws.send_json(payload)
        except Exception:
            pass

    async def _run_partial_transcription(snapshot: bytes):
        """Background task: transcribe accumulated audio and send partial result."""
        try:
            wav = pcm_to_wav(snapshot, sample_rate=SAMPLE_RATE)
            text = await transcribe_audio_bytes_async(wav)
            if text and text.strip() and _is_valid_transcript(text.strip()):
                await _send({"type": "partial_transcript", "text": text.strip()})
        except Exception as exc:
            print(f"[partial-stt] {exc}")

    try:
        while True:
            message = await ws.receive()

            # ── Text control messages ────────────────────────
            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type", "")

                # ── start_conversation ──
                if msg_type == "start_conversation":
                    session_id = str(uuid4())
                    audio_buffer = bytearray()
                    conversation_history = []
                    is_active = True
                    last_partial_time = time.time()

                    conversations_collection.insert_one({
                        "session_id": session_id,
                        "started_at": datetime.now(timezone.utc),
                        "status": "active",
                    })

                    await _send({"type": "conversation_started", "session_id": session_id})
                    continue

                # ── end_of_speech ──
                if msg_type == "end_of_speech":
                    if partial_task and not partial_task.done():
                        partial_task.cancel()

                    buf_len = len(audio_buffer)
                    buf_duration = buf_len / (SAMPLE_RATE * 2)  # 2 bytes per sample
                    print(f"[ws] end_of_speech — buffer={buf_len} bytes ({buf_duration:.1f}s)")

                    if not audio_buffer:
                        print("[ws] ERROR: empty audio buffer")
                        await _send({"type": "error", "message": "No audio received"})
                        continue

                    # ── Latency benchmarking ──────────────────
                    pipeline_start = time.time()
                    latency = {}

                    try:
                        # ── Stage 1: STT ─────────────────────
                        stt_start = time.time()

                        # Sub-stage: PCM → WAV conversion
                        wav_start = time.time()
                        pcm_bytes = bytes(audio_buffer)
                        wav = pcm_to_wav(pcm_bytes, sample_rate=SAMPLE_RATE)
                        wav_end = time.time()
                        wav_ms = round((wav_end - wav_start) * 1000)
                        print(f"[LATENCY][STT] PCM→WAV: {wav_ms} ms "
                              f"(pcm={len(pcm_bytes)} bytes, wav={len(wav)} bytes)")

                        # Sub-stage: Deepgram API call
                        api_start = time.time()
                        transcript = await transcribe_audio_bytes_async(wav)
                        transcript = (transcript or "").strip()
                        api_end = time.time()
                        api_ms = round((api_end - api_start) * 1000)

                        stt_end = time.time()
                        latency["stt_ms"] = round((stt_end - stt_start) * 1000)
                        latency["stt_wav_ms"] = wav_ms
                        latency["stt_api_ms"] = api_ms
                        print(f"[LATENCY][STT] Deepgram API: {api_ms} ms | "
                              f"Total STT: {latency['stt_ms']} ms | "
                              f"Result: {transcript!r}")

                        if not transcript or not _is_valid_transcript(transcript):
                            print(f"[LATENCY][STT] Transcript rejected by filter")
                            await _send({"type": "error", "message": "Could not transcribe audio"})
                            audio_buffer = bytearray()
                            continue

                        await _send({"type": "final_transcript", "text": transcript})

                        # Save user message
                        now = datetime.now(timezone.utc)
                        chat_messages_collection.insert_one({
                            "session_id": session_id,
                            "role": "user",
                            "content": transcript,
                            "message_type": "audio_transcript",
                            "created_at": now,
                        })

                        # ── Stage 2: LLM ─────────────────────
                        llm_start = time.time()
                        print(f"[LATENCY][LLM] Sending to Groq Llama 3.3: {transcript!r} "
                              f"(history={len(conversation_history)} msgs)")
                        full_response = ""
                        first_chunk_time = None
                        chunk_count = 0
                        async for chunk in process_message_stream(transcript, conversation_history):
                            if first_chunk_time is None:
                                first_chunk_time = time.time()
                                print(f"[LATENCY][LLM] First token: "
                                      f"{round((first_chunk_time - llm_start) * 1000)} ms")
                            chunk_count += 1
                            full_response += chunk
                            await _send({"type": "assistant_stream", "text": chunk})
                        llm_end = time.time()
                        latency["llm_total_ms"] = round((llm_end - llm_start) * 1000)
                        latency["llm_first_token_ms"] = round(((first_chunk_time or llm_end) - llm_start) * 1000)
                        latency["llm_chunks"] = chunk_count
                        print(f"[LATENCY][LLM] Done — {len(full_response)} chars, "
                              f"{chunk_count} chunks | "
                              f"First token: {latency['llm_first_token_ms']} ms | "
                              f"Total: {latency['llm_total_ms']} ms")

                        if not full_response.strip():
                            print("[LATENCY][LLM] WARNING: empty response")
                            await _send({"type": "error", "message": "No response generated"})
                            audio_buffer = bytearray()
                            continue

                        await _send({"type": "assistant_done", "text": full_response})

                        # ── Stage 3: TTS ─────────────────────
                        tts_start = time.time()
                        print(f"[LATENCY][TTS] Generating Deepgram Aura audio "
                              f"({len(full_response)} chars, "
                              f"~{len(full_response.split())} words)")
                        try:
                            tts_bytes = await text_to_speech_bytes_async(full_response)
                            tts_end = time.time()
                            latency["tts_ms"] = round((tts_end - tts_start) * 1000)
                            latency["tts_audio_bytes"] = len(tts_bytes)
                            latency["tts_text_chars"] = len(full_response)
                            audio_b64 = base64.b64encode(tts_bytes).decode("ascii")
                            await _send({"type": "tts_audio", "audio": audio_b64})
                            print(f"[LATENCY][TTS] Done — {len(tts_bytes)} bytes MP3 | "
                                  f"{latency['tts_ms']} ms | "
                                  f"b64 payload: {len(audio_b64)} chars")
                        except Exception as tts_exc:
                            tts_end = time.time()
                            latency["tts_ms"] = round((tts_end - tts_start) * 1000)
                            print(f"[LATENCY][TTS] FAILED after {latency['tts_ms']} ms: {tts_exc}")
                            await _send({"type": "tts_error", "message": str(tts_exc)})

                        # ── Pipeline total ────────────────────
                        pipeline_end = time.time()
                        latency["total_ms"] = round((pipeline_end - pipeline_start) * 1000)
                        latency["audio_duration_s"] = round(buf_duration, 2)

                        # Compute percentage breakdown
                        if latency["total_ms"] > 0:
                            pct_stt = round(latency["stt_ms"] / latency["total_ms"] * 100)
                            pct_llm = round(latency["llm_total_ms"] / latency["total_ms"] * 100)
                            pct_tts = round(latency["tts_ms"] / latency["total_ms"] * 100)
                        else:
                            pct_stt = pct_llm = pct_tts = 0

                        print(f"[LATENCY][PIPELINE] ══════════════════════════════")
                        print(f"[LATENCY][PIPELINE]  STT:   {latency['stt_ms']:>5} ms  ({pct_stt}%)  "
                              f"[wav={latency.get('stt_wav_ms', '?')}ms + api={latency.get('stt_api_ms', '?')}ms]")
                        print(f"[LATENCY][PIPELINE]  LLM:   {latency['llm_total_ms']:>5} ms  ({pct_llm}%)  "
                              f"[first_token={latency['llm_first_token_ms']}ms, {latency.get('llm_chunks', '?')} chunks]")
                        print(f"[LATENCY][PIPELINE]  TTS:   {latency['tts_ms']:>5} ms  ({pct_tts}%)  "
                              f"[{latency.get('tts_audio_bytes', '?')} bytes MP3]")
                        print(f"[LATENCY][PIPELINE]  TOTAL: {latency['total_ms']:>5} ms  "
                              f"(audio captured: {latency['audio_duration_s']}s)")
                        print(f"[LATENCY][PIPELINE] ══════════════════════════════")

                        # Send latency data to frontend for debug panel
                        await _send({"type": "latency", **latency})

                        # Save assistant message
                        chat_messages_collection.insert_one({
                            "session_id": session_id,
                            "role": "assistant",
                            "content": full_response,
                            "message_type": "text",
                            "created_at": datetime.now(timezone.utc),
                        })

                        # Update history for multi-turn context
                        conversation_history.append({"role": "user", "content": transcript})
                        conversation_history.append({"role": "assistant", "content": full_response})

                    except Exception as exc:
                        print(f"[ws] EXCEPTION in end_of_speech: {exc}")
                        await _send({"type": "error", "message": f"Processing failed: {exc}"})
                    finally:
                        audio_buffer = bytearray()
                        last_partial_time = time.time()
                    continue

                # ── stop_conversation ──
                if msg_type == "stop_conversation":
                    is_active = False
                    if partial_task and not partial_task.done():
                        partial_task.cancel()
                    if session_id:
                        conversations_collection.update_one(
                            {"session_id": session_id},
                            {"$set": {"status": "ended", "ended_at": datetime.now(timezone.utc)}},
                        )
                    break

            # ── Binary audio chunks ──────────────────────────
            elif "bytes" in message:
                if not is_active:
                    continue
                chunk_len = len(message["bytes"])
                audio_buffer.extend(message["bytes"])
                buf_duration = len(audio_buffer) / (SAMPLE_RATE * 2)
                # Log every ~1 s of accumulated audio
                if int(buf_duration) != int((len(audio_buffer) - chunk_len) / (SAMPLE_RATE * 2)):
                    print(f"[ws] Audio buffer: {len(audio_buffer)} bytes ({buf_duration:.1f}s)")

                # Fire periodic partial transcription
                now_ts = time.time()
                if (now_ts - last_partial_time >= PARTIAL_TRANSCRIPTION_INTERVAL
                        and len(audio_buffer) > SAMPLE_RATE * 2):  # at least 1s of audio
                    last_partial_time = now_ts
                    snapshot = bytes(audio_buffer)
                    if partial_task and not partial_task.done():
                        partial_task.cancel()
                    partial_task = asyncio.create_task(
                        _run_partial_transcription(snapshot)
                    )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[ws] unexpected: {exc}")
    finally:
        if partial_task and not partial_task.done():
            partial_task.cancel()
        if session_id:
            conversations_collection.update_one(
                {"session_id": session_id},
                {"$set": {"status": "ended", "ended_at": datetime.now(timezone.utc)}},
            )


# ── Static files ─────────────────────────────────────────────

app.mount("/audio", StaticFiles(directory="audio"), name="audio")