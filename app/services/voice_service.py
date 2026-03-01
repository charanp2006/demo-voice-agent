import os 
from groq import Groq
from dotenv import load_dotenv
from gtts import gTTS

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def transcribe_audio(file_path: str):
    # Simulate transcription process
    with open(file_path, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3"
        )
    return transcription.text

def text_to_speech(text: str, output_path: str):
    tts = gTTS(text=text, lang='en')
    tts.save(output_path)
    # return output_path