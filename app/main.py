from fastapi import FastAPI, UploadFile, File
from app.routers import clinic
from pydantic import BaseModel
from app.services.agent_service import process_message
from app.services.voice_service import transcribe_audio, text_to_speech
from fastapi.responses import FileResponse
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
    temp_input = f"temp_{file.filename}"
    temp_output = "response.mp3"

    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Step 1: Transcribe
    user_text = transcribe_audio(temp_input)

    # Step 2: Send to agent
    response_text = process_message(user_text)

    # return {
    #     "transcription": user_text,
    #     "response": response_text
    # }

    # Step 3: Convert response to speech
    text_to_speech(response_text, temp_output)

    return FileResponse(temp_output, media_type="audio/mpeg")