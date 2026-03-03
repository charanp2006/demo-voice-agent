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
        audio_generator = eleven_client.text_to_speech.convert(
            text=text,
            # voice_id="SAz9YHcvj6GT2YYXdXww",  # River - Relaxed, Neutral, Informative
            voice_id="IKne3meq5aSn9XLyUdCD",  # Charlie - Deep, Confident, Energetic
            model_id="eleven_turbo_v2"
            
            # Other male voice options:
            # voice_id="cjVigY5qzO86Huf0OWal",  # Eric - Smooth, Trustworthy
            # voice_id="nPczCjzI2devNBz1zQrb",  # Brian - Deep, Resonant and Comforting
            # voice_id="IKne3meq5aSn9XLyUdCD",  # Charlie - Deep, Confident, Energetic
        )
        # Convert generator to bytes
        audio_content = b"".join(audio_generator)
        with open(output_path, "wb") as audio_file:
            audio_file.write(audio_content)

        print("Audio generated using ElevenLabs.")

    except Exception as e:
        print(f"ElevenLabs TTS failed: {e}. Falling back to gTTS.")

        # tts = gTTS(text=text, lang='en')
        # tts.save(output_path)
    return output_path


def get_available_voices():
    """Get all available voices from ElevenLabs"""
    try:
        voices = eleven_client.voices.get_all()
        voice_list = []
        for voice in voices.voices:
            voice_list.append({
                "name": voice.name,
                "voice_id": voice.voice_id
            })
            print(f"{voice.name}: {voice.voice_id}")
        return voice_list
    except Exception as e:
        print(f"Error fetching voices: {e}")
        return []
