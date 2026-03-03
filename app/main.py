from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import base64

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from app.routers import clinic
from pydantic import BaseModel
from app.services.agent_service import process_message
from app.services.voice_service import transcribe_audio, text_to_speech
from fastapi.responses import FileResponse
from app.database import chat_collection
import shutil

app = FastAPI()

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

class ChatRequest(BaseModel):
    message: str


def _serialize_chat_message(message: dict):
    message["_id"] = str(message["_id"])
    created_at = message.get("created_at")
    if created_at and isinstance(created_at, datetime):
        message["created_at"] = created_at.isoformat()
    return message


def _generate_tts_base64(text: str):
    output_name = f"tts_{uuid4().hex}.mp3"
    output_path = AUDIO_DIR / output_name
    text_to_speech(text, str(output_path))

    with open(output_path, "rb") as audio_file:
        audio_bytes = audio_file.read()

    try:
        output_path.unlink(missing_ok=True)
    except Exception:
        pass

    return base64.b64encode(audio_bytes).decode("utf-8")


@app.get("/history")
def get_history(limit: int = 50):
    safe_limit = max(1, min(limit, 200))
    messages = list(chat_collection.find().sort("created_at", -1).limit(safe_limit))
    messages.reverse()
    return {"messages": [_serialize_chat_message(message) for message in messages]}

# --- Chat Endpoint --- #
@app.post("/chat")
def chat(request: ChatRequest):
    reply = process_message(request.message)
    audio_base64 = _generate_tts_base64(reply)
    now = datetime.now(timezone.utc)
    chat_collection.insert_many([
        {"role": "user", "content": request.message, "created_at": now},
        {"role": "assistant", "content": reply, "created_at": now},
    ])
    return {
        "response": reply,
        "audio_base64": audio_base64,
        "audio_mime_type": "audio/mpeg"
    }


# --- Test STT Endpoint --- #
@app.post("/test-stt")
async def test_stt(file: UploadFile = File(...)):

    # Save the uploaded file to a temporary location
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Transcribe the audio file
    text = transcribe_audio(file_location)
    return {"transcription": text}


# --- Test TTS Endpoint --- #
@app.post("/test-tts")
async def test_tts(request: ChatRequest):
    
    # Generate audio from text
    temp_output = "test_tts_output.mp3"
    text_to_speech(request.message, temp_output)
    
    return FileResponse(temp_output, media_type="audio/mpeg")


@app.post("/voice")
async def voice_endpoint(file: UploadFile = File(...)):

    # Save the uploaded file to a temporary location
    input_name = f"temp_{uuid4().hex}_{file.filename}"
    temp_input = BASE_DIR.parent / input_name

    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Step 1: Transcribe
    user_text = transcribe_audio(str(temp_input))

    # Step 2: Send to agent
    response_text = process_message(user_text)

    # Step 3: Convert response to speech
    audio_base64 = _generate_tts_base64(response_text)

    now = datetime.now(timezone.utc)
    chat_collection.insert_many([
        {"role": "user", "content": user_text, "created_at": now},
        {"role": "assistant", "content": response_text, "created_at": now},
    ])

    try:
        temp_input.unlink(missing_ok=True)
    except Exception:
        pass

    return {
        "transcription": user_text,
        "response": response_text,
        "audio_base64": audio_base64,
        "audio_mime_type": "audio/mpeg"
    }