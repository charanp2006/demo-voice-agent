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

@app.post("/chat")
def chat(request: ChatRequest):
    reply = process_message(request.message)
    return {"response": reply}

@app.post("/test-stt")
async def test_stt(file: UploadFile = File(...)):

    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    text = transcribe_audio(file_location)
    return {"transcription": text}