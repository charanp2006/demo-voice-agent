from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))

db = client["voice_agent_db"]

appointments_collection = db["appointments"]
chat_collection = db["chat_messages"]