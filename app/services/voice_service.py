"""
Voice service – Dual STT/TTS backends for latency benchmarking.

Active:  **Deepgram Nova-3** (STT) + **Deepgram Aura** (TTS)
Backup:  Groq Whisper (STT) + ElevenLabs / gTTS (TTS) — commented out.

Provides both sync helpers and async wrappers for the WebSocket handler.
"""

import io
import os
import wave
import asyncio
import httpx

from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# ── PCM ↔ WAV helpers ───────────────────────────────────────

def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000,
               channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM-16 LE bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════
# ── Active STT: Deepgram Nova-3 ─────────────────────────────
# ══════════════════════════════════════════════════════════════

def transcribe_audio_bytes(wav_bytes: bytes) -> str:
    """Transcribe from in-memory WAV bytes via Deepgram Nova-3."""
    url = "https://api.deepgram.com/v1/listen"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/wav",
    }
    params = {
        "model": "nova-3",
        "language": "en",
        "smart_format": "true",
        "punctuate": "true",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, params=params, content=wav_bytes)
        resp.raise_for_status()
        data = resp.json()
    # Extract transcript from Deepgram response
    try:
        return data["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError):
        return ""


async def transcribe_audio_bytes_async(wav_bytes: bytes) -> str:
    """Non-blocking Deepgram STT via async HTTP."""
    url = "https://api.deepgram.com/v1/listen"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/wav",
    }
    params = {
        "model": "nova-3",
        "language": "en",
        "smart_format": "true",
        "punctuate": "true",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, params=params, content=wav_bytes)
        resp.raise_for_status()
        data = resp.json()
    try:
        return data["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError):
        return ""


# ══════════════════════════════════════════════════════════════
# ── Active TTS: Deepgram Aura ───────────────────────────────
# ══════════════════════════════════════════════════════════════

def text_to_speech(text: str, output_path: str) -> str:
    """Generate an MP3 file from text via Deepgram Aura."""
    url = "https://api.deepgram.com/v1/speak"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }
    params = {"model": "aura-asteria-en", "encoding": "mp3"}
    payload = {"text": text}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, params=params, json=payload)
        resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)
    return output_path


def text_to_speech_bytes(text: str) -> bytes:
    """Return MP3 bytes from Deepgram Aura without writing to disk."""
    url = "https://api.deepgram.com/v1/speak"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }
    params = {"model": "aura-asteria-en", "encoding": "mp3"}
    payload = {"text": text}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, params=params, json=payload)
        resp.raise_for_status()
    return resp.content


async def text_to_speech_bytes_async(text: str) -> bytes:
    """Non-blocking Deepgram Aura TTS via async HTTP."""
    url = "https://api.deepgram.com/v1/speak"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }
    params = {"model": "aura-asteria-en", "encoding": "mp3"}
    payload = {"text": text}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, params=params, json=payload)
        resp.raise_for_status()
    return resp.content


# ══════════════════════════════════════════════════════════════
# ── COMMENTED OUT: Groq Whisper STT + ElevenLabs/gTTS TTS ───
# Uncomment to switch back for benchmarking.
# ══════════════════════════════════════════════════════════════
#
# from groq import Groq
# from gtts import gTTS
# from elevenlabs.client import ElevenLabs
#
# groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
# eleven_client = ElevenLabs(api_key=os.getenv("ELEVEN_API_KEY"))
#
# def transcribe_audio(file_path: str) -> str:
#     with open(file_path, "rb") as f:
#         result = groq_client.audio.transcriptions.create(file=f, model="whisper-large-v3")
#     return result.text
#
# def transcribe_audio_bytes(wav_bytes: bytes) -> str:
#     buf = io.BytesIO(wav_bytes)
#     buf.name = "audio.wav"
#     result = groq_client.audio.transcriptions.create(file=buf, model="whisper-large-v3")
#     return result.text
#
# async def transcribe_audio_bytes_async(wav_bytes: bytes) -> str:
#     return await asyncio.to_thread(transcribe_audio_bytes, wav_bytes)
#
# def text_to_speech(text: str, output_path: str) -> str:
#     try:
#         audio_gen = eleven_client.text_to_speech.convert(
#             text=text, voice_id="nwj0s2LU9bDWRKND5yzA", model_id="eleven_turbo_v2")
#         audio_content = b"".join(audio_gen)
#         with open(output_path, "wb") as f:
#             f.write(audio_content)
#     except Exception as exc:
#         print(f"[TTS] ElevenLabs failed ({exc}), falling back to gTTS")
#         tts = gTTS(text=text, lang="en")
#         tts.save(output_path)
#     return output_path
#
# def text_to_speech_bytes(text: str) -> bytes:
#     try:
#         audio_gen = eleven_client.text_to_speech.convert(
#             text=text, voice_id="wvYsNKX8YWSlLtSB2UOH", model_id="eleven_turbo_v2")
#         return b"".join(audio_gen)
#     except Exception:
#         buf = io.BytesIO()
#         tts = gTTS(text=text, lang="en")
#         tts.write_to_fp(buf)
#         return buf.getvalue()
#
# async def text_to_speech_bytes_async(text: str) -> bytes:
#     return await asyncio.to_thread(text_to_speech_bytes, text)
