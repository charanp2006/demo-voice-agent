"""
Voice service – Speech-to-Text (Groq Whisper) and Text-to-Speech (ElevenLabs / gTTS).

Provides both sync helpers and an async wrapper for use inside the WebSocket handler.
"""

import io
import os
import wave
import asyncio

from groq import Groq
from dotenv import load_dotenv
from gtts import gTTS
from elevenlabs.client import ElevenLabs

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.getenv("ELEVEN_API_KEY"))


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


# ── STT ──────────────────────────────────────────────────────

def transcribe_audio(file_path: str) -> str:
    """Transcribe an audio file on disk (any format Whisper accepts)."""
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3",
        )
    return result.text


def transcribe_audio_bytes(wav_bytes: bytes) -> str:
    """Transcribe from an in-memory WAV byte string."""
    buf = io.BytesIO(wav_bytes)
    buf.name = "audio.wav"
    result = groq_client.audio.transcriptions.create(
        file=buf,
        model="whisper-large-v3",
    )
    return result.text


async def transcribe_audio_bytes_async(wav_bytes: bytes) -> str:
    """Non-blocking wrapper – runs Whisper in a thread."""
    return await asyncio.to_thread(transcribe_audio_bytes, wav_bytes)


# ── TTS ──────────────────────────────────────────────────────

def text_to_speech(text: str, output_path: str) -> str:
    """Generate an MP3 file from *text*.  Tries ElevenLabs first, falls back to gTTS."""
    try:
        audio_gen = eleven_client.text_to_speech.convert(
            text=text,
            voice_id="SAz9YHcvj6GT2YYXdXww",
            model_id="eleven_turbo_v2",
        )
        audio_content = b"".join(audio_gen)
        with open(output_path, "wb") as f:
            f.write(audio_content)
    except Exception as exc:
        print(f"[TTS] ElevenLabs failed ({exc}), falling back to gTTS")
        tts = gTTS(text=text, lang="en")
        tts.save(output_path)
    return output_path


def text_to_speech_bytes(text: str) -> bytes:
    """Return MP3 bytes without writing to disk."""
    try:
        audio_gen = eleven_client.text_to_speech.convert(
            text=text,
            voice_id="SAz9YHcvj6GT2YYXdXww",
            model_id="eleven_turbo_v2",
        )
        return b"".join(audio_gen)
    except Exception:
        buf = io.BytesIO()
        tts = gTTS(text=text, lang="en")
        tts.write_to_fp(buf)
        return buf.getvalue()


async def text_to_speech_bytes_async(text: str) -> bytes:
    """Non-blocking TTS wrapper."""
    return await asyncio.to_thread(text_to_speech_bytes, text)
