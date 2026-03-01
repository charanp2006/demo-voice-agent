from fastapi import FastAPI, UploadFile, File
from app.routers import clinic
from pydantic import BaseModel
from app.services.agent_service import process_message
from app.services.voice_service import transcribe_audio
import shutil

app = FastAPI()

app.include_router(clinic.router)

class ChatRequest(BaseModel):
    message: str

# --- Chat Endpoint --- #
@app.post("/chat")
def chat(request: ChatRequest):
    reply = process_message(request.message)
    return {"response": reply}


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

@app.post("/voice")
async def voice_endpoint(file: UploadFile = File(...)):

    # Save the uploaded file to a temporary location
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Step 1: Transcribe
    user_text = transcribe_audio(file_location)

    # Step 2: Send to agent
    response_text = process_message(user_text)
    return {
        "transcription": user_text,
        "response": response_text
    }