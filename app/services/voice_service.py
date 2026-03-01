import os 
from groq import Groq
from dotenv import load_dotenv
from gtts import gTTS
from elevenlabs.client import ElevenLabs

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.getenv("ELEVEN_API_KEY"))

def transcribe_audio(file_path: str):
    # Simulate transcription process
    with open(file_path, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3"
        )
    return transcription.text

def text_to_speech(text: str, output_path: str):

    try:
        # Try using ElevenLabs first
        audio_content = eleven_client.text_to_speech.convert(
            text=text,
            voice="Rachel",
            model="eleven_monolingual_v1"
            # voice_id="EXAVITQu4vr4xnSDxMaL",  # Default Eleven voice
            # model_id="eleven_monolingual_v1"
        )
        with open(output_path, "wb") as audio_file:
            audio_file.write(audio_content)

        print("Audio generated using ElevenLabs.")

    except Exception as e:
        print(f"ElevenLabs TTS failed: {e}. Falling back to gTTS.")

        tts = gTTS(text=text, lang='en')
        tts.save(output_path)
    # return output_path
