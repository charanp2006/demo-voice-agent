from fastapi import FastAPI
from app.routers import clinic
from pydantic import BaseModel
from app.services.agent_service import procces_message

app = FastAPI()

app.include_router(clinic.router)

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
def chat(request: ChatRequest):
    reply = procces_message(request.message)
    return {"response": reply}
