# Frontend (React + Vite + Tailwind)

Chat-style voice assistant frontend for the clinic app.

## Features

- Chat interface with message history
- Bottom text composer with send button
- Mic toggle button (tap to start recording, tap again to stop/send)
- Auto playback of TTS audio returned by backend
- Loading indicator while backend processes requests

## Prerequisites

- Node.js 18+
- Backend running at `http://localhost:8000` (default)

## Run

```bash
npm install
npm run dev
```

App runs on `http://localhost:5173`.

## Optional Environment Variable

Create a `.env` file in `frontend/` if backend URL differs:

```bash
VITE_API_BASE=http://localhost:8000
```

## API Contract Used by Frontend

### `POST /voice`
Request: `multipart/form-data` with `file` audio blob.

Response JSON:

```json
{
  "transcription": "user speech text",
  "response": "assistant text",
  "audio_base64": "<base64-mp3>",
  "audio_mime_type": "audio/mpeg"
}
```

Frontend behavior:
- Appends `transcription` as user chat message
- Appends `response` as assistant chat message
- Decodes `audio_base64` and auto-plays TTS

### `POST /chat`
Request JSON:

```json
{ "message": "text input" }
```

Response JSON:

```json
{
  "response": "assistant text",
  "audio_base64": "<base64-mp3>",
  "audio_mime_type": "audio/mpeg"
}
```

Frontend behavior:
- Appends text messages to chat
- Auto-plays returned TTS audio

### `GET /history`
Loads prior chat messages for the panel.

## Complete Architecture Workflow

### End-to-End Voice Flow

```mermaid
sequenceDiagram
  autonumber
  participant U as User
  participant FE as React Frontend
  participant API as FastAPI (/voice)
  participant STT as STT Service
  participant AG as Agent/LLM
  participant DB as MongoDB
  participant TTS as TTS Service

  U->>FE: Tap mic (start recording)
  U->>FE: Tap mic again (stop recording)
  FE->>API: POST /voice (audio blob)
  API->>STT: Transcribe audio
  STT-->>API: transcription text
  API->>AG: Validate/process user intent
  AG->>DB: Read/Write data (appointments/chat)
  DB-->>AG: DB result
  AG-->>API: assistant response text
  API->>TTS: Generate speech from response
  TTS-->>API: MP3 bytes
  API-->>FE: JSON {transcription, response, audio_base64}
  FE->>FE: Render user + assistant messages
  FE->>U: Auto-play TTS audio
```

### System Architecture (Components)

```mermaid
flowchart LR
  U[User]
  FE[React Chat UI\nText Input + Mic Toggle + Audio Player]
  API[FastAPI Backend]
  STT[Speech-to-Text]
  AG[Agent / LLM Orchestration]
  DB[(MongoDB)]
  TTS[Text-to-Speech]

  U --> FE
  FE -->|POST /voice| API
  FE -->|POST /chat| API
  FE -->|GET /history| API

  API --> STT
  STT --> API
  API --> AG
  AG --> DB
  DB --> AG
  AG --> API
  API --> TTS
  TTS --> API

  API -->|JSON + audio_base64| FE
  FE -->|Auto playback + chat update| U
```
