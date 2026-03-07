# SmileCare Dental Clinic – AI Voice Conversation System

## System Architecture (Mermaid)

### High-Level System Overview

```mermaid
graph TB
    subgraph Frontend["Frontend (React + Vite)"]
        UI["Start / Stop Buttons"]
        AW["AudioWorklet Processor<br/>16 kHz PCM + RMS + Peak"]
        VAD_FE["Sliding-Window VAD<br/>Calibration · Crest Factor · Audio Gating"]
        WSC["WebSocket Client"]
        TTS_P["TTS Playback<br/>Word-by-Word Reveal + Barge-in"]
        SD["Chat Display<br/>Partial Transcript · Final Transcript<br/>TTS Word Reveal · Debug Panel"]
    end

    subgraph Backend["Backend (FastAPI)"]
        WSH["WebSocket Handler<br/>(main.py)"]
        BUF["Audio Buffer<br/>(bytearray)"]
        STT["Deepgram Nova-3<br/>Speech-to-Text"]
        FILTER["Transcript Filter<br/>Hallucination Blocklist"]
        AGT["Agent Service<br/>Dental Validation"]
        LLM["Groq Llama 3.3 70B<br/>+ Function Calling"]
        TTS_GEN["TTS Generation<br/>Deepgram Aura"]
        TOOLS["Tool Handlers<br/>check_slots · book · cancel<br/>reschedule · services · info<br/>dentists · patient_appts"]
        VAPI_WH["Vapi Webhook<br/>POST /vapi/webhook"]
    end

    subgraph DB["MongoDB"]
        COLS["patients · dentists · dental_services<br/>appointments · treatment_records<br/>conversations · chat_messages"]
    end

    UI --> AW
    AW -->|"RMS + Peak"| VAD_FE
    AW -->|"audio chunks"| VAD_FE
    VAD_FE -->|"binary PCM<br/>(only when speech confirmed)"| WSC
    VAD_FE -->|"end_of_speech"| WSC
    WSC -->|"WebSocket ws://…/ws/voice"| WSH
    WSH --> BUF
    BUF -->|"periodic (~2s)"| STT
    BUF -->|"end_of_speech"| STT
    STT -->|"text"| FILTER
    FILTER -->|"partial_transcript"| WSH
    FILTER -->|"final_transcript"| AGT
    AGT --> LLM
    LLM -->|"tool_call"| TOOLS
    TOOLS -->|"result"| LLM
    LLM -->|"streaming chunks"| WSH
    WSH -->|"assistant_done (full text)"| TTS_GEN
    TTS_GEN -->|"base64 MP3 (tts_audio)"| WSH
    TOOLS --> DB
    WSH -->|"partial_transcript<br/>final_transcript<br/>assistant_stream<br/>assistant_done<br/>tts_audio"| SD
    WSH -->|"tts_audio"| TTS_P
    TTS_P -->|"🔊 audio + word reveal"| SD
    TTS_P -.->|"Barge-in<br/>(user speaks)"| VAD_FE
    VAPI_WH -->|"tool dispatch"| TOOLS

    style Frontend fill:#e0f2fe,stroke:#0284c7
    style Backend fill:#f0fdf4,stroke:#16a34a
    style DB fill:#fef9c3,stroke:#ca8a04
```

### WebSocket Conversation Flow

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend<br/>(React + AudioWorklet)
    participant WS as WebSocket
    participant BE as Backend<br/>(FastAPI)
    participant STT as Deepgram Nova-3
    participant LLM as Groq Llama 3 LLM
    participant DB as MongoDB

    U->>FE: Tap "Start Conversation"
    FE->>WS: { type: start_conversation }
    WS->>BE: open session
    BE->>DB: Insert conversation record
    BE->>WS: { type: conversation_started, session_id }
    WS->>FE: Display "Calibrating..." (2s)
    FE->>FE: Start mic → AudioWorklet → Noise-floor calibration
    Note over FE: After 2s: calibration done, threshold computed
    WS->>FE: Display "Listening…"

    loop While user speaks (speech confirmed by sliding-window VAD)
        FE->>WS: binary PCM audio chunks (gated: only when speech confirmed)
        WS->>BE: Append to audio_buffer
    end

    Note over BE: Every ~2 seconds
    BE->>STT: Transcribe buffer snapshot
    STT-->>BE: partial text
    Note over BE: Filter hallucinations
    BE->>WS: { type: partial_transcript, text }
    WS->>FE: Show "What is the…" (italic, typing)

    Note over FE: VAD detects 2s silence
    FE->>WS: { type: end_of_speech }
    WS->>BE: Final STT request

    BE->>STT: Transcribe full buffer
    STT-->>BE: final text
    Note over BE: Validate transcript (length, hallucinations)
    BE->>WS: { type: final_transcript, text }
    WS->>FE: Finalize user bubble
    BE->>DB: Save user message

    BE->>LLM: Send transcript + history
    Note over LLM: May trigger tool calls
    LLM->>BE: tool_call: check_slots("2026-03-06")
    BE->>DB: Query available slots
    DB-->>BE: results
    BE->>LLM: Function response with results
    LLM-->>BE: Streaming text chunks

    loop For each chunk
        BE->>WS: { type: assistant_stream, text: "Here are…" }
        WS->>FE: Buffer silently (not shown yet)
    end

    BE->>WS: { type: assistant_done, text: full_response }
    WS->>FE: Store full text, wait for TTS
    BE->>DB: Save assistant message

    Note over BE: Generate TTS (Deepgram Aura)
    BE->>WS: { type: tts_audio, audio: base64_mp3 }
    WS->>FE: Play audio + reveal words one-by-one
    Note over FE: 🔊 Assistant speaks, words appear in sync

    alt User interrupts (barge-in)
        U->>FE: Speaks during TTS
        Note over FE: VAD detects speech (threshold ×2.5)
        FE->>FE: stopTTS() → pause audio, commit text
        FE->>WS: binary PCM chunks (new utterance)
    end

    Note over FE: TTS ends → resumes listening

    U->>FE: Tap "Stop Conversation"
    FE->>WS: { type: stop_conversation }
    WS->>BE: Close session
    BE->>DB: Update conversation status → ended
    FE->>FE: Stop mic, close WebSocket
```

### Agent Tool-Calling Decision Flow

```mermaid
flowchart TD
    A[User transcript received] --> B{Is it dental-related?}
    B -->|No| C["Politely decline:<br/>'I can only help with dental care'"]
    B -->|Yes| D{Does it require an action?}
    D -->|No| E[General dental advice<br/>Stream text response]
    D -->|Yes| F{Which action?}

    F --> G[check_available_slots]
    F --> H[book_appointment]
    F --> I[cancel_appointment]
    F --> J[reschedule_appointment]
    F --> K[get_dental_services]
    F --> L[get_clinic_info]
    F --> M[get_dentists]
    F --> N[get_patient_appointments]

    G --> O{Missing fields?}
    H --> O
    I --> O
    J --> O
    K --> P[Execute tool]
    L --> P
    M --> P
    N --> O

    O -->|Yes| Q[Ask user for<br/>missing information]
    O -->|No| P

    P --> R[Feed result back to LLM]
    R --> S[Stream final response<br/>to user via WebSocket]

    style A fill:#dbeafe,stroke:#2563eb
    style C fill:#fee2e2,stroke:#dc2626
    style E fill:#d1fae5,stroke:#059669
    style S fill:#d1fae5,stroke:#059669
    style Q fill:#fef3c7,stroke:#d97706
```

### Audio Pipeline (AudioWorklet → STT)

```mermaid
flowchart LR
    MIC["🎤 Microphone<br/>48 kHz"] --> AWS["AudioWorklet<br/>Processor"]
    AWS -->|"Downsample<br/>48→16 kHz"| PCM["PCM-16 LE<br/>Float32 chunks"]
    AWS -->|"RMS + Peak"| VAD["Sliding-Window VAD<br/>(main thread)"]
    PCM -->|"Pre-speech buffer<br/>(15 chunks ≈ 3.8s)"| GATE{"Speech<br/>Confirmed?"}
    GATE -->|"Yes: flush + stream"| WS["WebSocket"]
    GATE -->|"No: ring buffer"| PCM
    VAD -->|"2s silence"| EOS["end_of_speech<br/>JSON message"]
    EOS --> WS
    WS --> SRV["FastAPI<br/>Server"]
    SRV -->|"pcm_to_wav()"| WAV["WAV container"]
    WAV --> WHISPER["Deepgram Nova-3"]
    WHISPER --> FILTER["Hallucination<br/>Filter"]
    FILTER --> TXT["Transcript text"]
    SRV -->|"After LLM response"| TTS_GEN["Deepgram Aura<br/>TTS"]
    TTS_GEN -->|"Base64 MP3"| WS2["tts_audio→Client"]
    WS2 --> PLAY["🔊 Playback<br/>+ Word Reveal"]

    style MIC fill:#dbeafe,stroke:#2563eb
    style WHISPER fill:#f3e8ff,stroke:#7c3aed
    style TXT fill:#d1fae5,stroke:#059669
    style TTS_GEN fill:#fce7f3,stroke:#db2777
    style PLAY fill:#fce7f3,stroke:#db2777
```

### Database Entity Relationships

```mermaid
erDiagram
    PATIENTS {
        string name
        string phone PK
        string email
        string date_of_birth
        string gender
        string address
        string medical_history
        array allergies
        object emergency_contact
        datetime created_at
        datetime updated_at
    }

    DENTISTS {
        string name
        string specialization
        string phone
        string email
        array available_days
        object working_hours
        datetime created_at
    }

    DENTAL_SERVICES {
        string name
        string category
        string description
        int duration_minutes
        float price
        boolean is_active
        datetime created_at
    }

    APPOINTMENTS {
        string patient_name
        string patient_phone FK
        string date
        string time
        string service
        string dentist_name
        string status
        string notes
        datetime created_at
        datetime updated_at
    }

    TREATMENT_RECORDS {
        string patient_phone FK
        string appointment_id FK
        string dentist_name
        string service_name
        string diagnosis
        string treatment_notes
        string prescription
        string follow_up_date
        datetime created_at
    }

    CONVERSATIONS {
        string session_id PK
        datetime started_at
        datetime ended_at
        string status
    }

    CHAT_MESSAGES {
        string session_id FK
        string role
        string content
        string message_type
        datetime created_at
    }

    PATIENTS ||--o{ APPOINTMENTS : "books"
    DENTISTS ||--o{ APPOINTMENTS : "assigned to"
    DENTAL_SERVICES ||--o{ APPOINTMENTS : "service type"
    PATIENTS ||--o{ TREATMENT_RECORDS : "has"
    APPOINTMENTS ||--o| TREATMENT_RECORDS : "generates"
    CONVERSATIONS ||--o{ CHAT_MESSAGES : "contains"
```

---

## System Architecture (ASCII)

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite)                         │
│                                                                        │
│  ┌────────────┐   ┌──────────────────┐   ┌──────────────────┐         │
│  │  Start /    │   │  AudioWorklet    │   │  WebSocket       │         │
│  │  Stop Btns  │──>│  Processor       │──>│  Client          │         │
│  └────────────┘   │  (16kHz PCM)     │   │                  │         │
│                    │  + RMS + Peak    │   │  ┌────────────┐  │         │
│                    └───────┬──────────┘   │  │ audio_chunk │──┼──> binary PCM
│                            │              │  │ end_speech  │──┼──> JSON ctrl
│                            ▼              │  └────────────┘  │         │
│                  ┌──────────────────┐     │                  │         │
│                  │ Sliding-Window   │     │                  │         │
│                  │ VAD (main thread)│     │                  │         │
│                  │ • Calibration    │     │                  │         │
│                  │ • Crest factor   │     │                  │         │
│                  │ • Audio gating   │     │                  │         │
│                  │ • Pre-speech buf │     │                  │         │
│                  │ • TTS barge-in   │     │                  │         │
│                  └──────────────────┘     │                  │         │
│                                           │                  │         │
│  ┌──────────────────────────────────────┐ │                  │         │
│  │  Chat Display                        │ │                  │         │
│  │  - partial_transcript (italic)       │<┼──partial_txn     │         │
│  │  - final_transcript → chat bubble    │<┼──final_txn       │         │
│  │  - assistant_stream → buffered       │<┼──asst_stream     │         │
│  │  - assistant_done → store text       │<┼──asst_done       │         │
│  │  - tts_audio → 🔊 word-by-word      │<┼──tts_audio       │         │
│  └──────────────────────────────────────┘ └──────────────────┘         │
│                                                                        │
│  ┌──────────────────────────────────────┐                              │
│  │  TTS Playback Engine                 │                              │
│  │  - Decode base64 → Blob → Audio     │                              │
│  │  - Word-by-word reveal (setInterval) │                              │
│  │  - Barge-in: stopTTS() on speech     │                              │
│  │  - Fallback: show text on error      │                              │
│  └──────────────────────────────────────┘                              │
│                                                                        │
│  ┌─────────────────────┐                                               │
│  │  Debug Panel         │  Collapsible, timestamped, color-coded logs  │
│  └─────────────────────┘                                               │
└────────────────────────────────────────────────────────────────────────┘
                              │  WebSocket (ws://…/ws/voice)
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI + WebSocket)                       │
│                                                                        │
│  ┌──────────────┐   ┌──────────────────┐   ┌────────────────┐         │
│  │  WS Handler  │──>│  Audio Buffer    │──>│  Deepgram       │         │
│  │  (main.py)   │   │  (bytearray)     │   │  Nova-3 STT     │         │
│  └──────┬───────┘   └──────────────────┘   └───────┬────────┘         │
│         │                                           │                  │
│         │  periodic (every ~2s)                     ▼                  │
│         │  ──────────────────>  partial_transcript                     │
│         │                      (hallucination filter applied)          │
│         │                                                              │
│         │  end_of_speech                                               │
│         │  ──────────────────>  final_transcript                       │
│         │                            │                                 │
│         │                            ▼                                 │
│         │                  ┌──────────────────┐                        │
│         │                  │  Agent Service    │                        │
│         │                  │  ┌────────────┐  │                        │
│         │                  │  │ Dental      │  │                        │
│         │                  │  │ Validation  │  │                        │
│         │                  │  └────────────┘  │                        │
│         │                  │  ┌────────────┐  │                        │
│         │                  │  │ Groq Llama  │  │                        │
│         │                  │  │ 3.3 70B     │  │                        │
│         │                  │  │ + Tool Call │  │                        │
│         │                  └────────┼─────────┘                        │
│         │                           │                                  │
│         │                           ▼                                  │
│         │                  ┌──────────────────┐                        │
│         │                  │  Tool Handlers    │                        │
│         │                  │  - check_slots    │                        │
│         │                  │  - book_appt      │                        │
│         │                  │  - cancel_appt    │                        │
│         │                  │  - reschedule     │                        │
│         │                  │  - get_services   │                        │
│         │                  │  - get_info       │                        │
│         │                  │  - get_dentists   │                        │
│         │                  │  - get_patient    │                        │
│         │                  └────────┬─────────┘                        │
│         │                           │                                  │
│         │            streaming chunks│                                  │
│         │<──── assistant_stream ─────┘                                  │
│         │<──── assistant_done (with full text)                          │
│         │                                                              │
│         │      ┌──────────────────────────┐                            │
│         │──────│  TTS Generation          │                            │
│         │      │  Deepgram Aura           │                            │
│         │      └──────────┬───────────────┘                            │
│         │<──── tts_audio (base64 MP3)                                  │
│         │<──── tts_error (on failure)                                  │
│         │                                                              │
│         ▼                                                              │
│  ┌──────────────┐                                                      │
│  │  MongoDB      │  Collections:                                        │
│  │               │  - patients           - conversations                │
│  │               │  - dentists           - chat_messages                │
│  │               │  - dental_services                                   │
│  │               │  - appointments                                      │
│  │               │  - treatment_records                                 │
│  └──────────────┘                                                      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## WebSocket Message Schema

### Client → Server

| Message | Format | Description |
|---------|--------|-------------|
| `start_conversation` | `{ "type": "start_conversation" }` | Opens a new session, mic starts automatically |
| `audio_chunk` | **Binary** (PCM-16 LE, 16 kHz, mono) | Raw audio from AudioWorklet, sent continuously |
| `end_of_speech` | `{ "type": "end_of_speech" }` | VAD detected 2 s silence → triggers final STT + LLM |
| `stop_conversation` | `{ "type": "stop_conversation" }` | Ends session, closes connection |

### Server → Client

| Message | Format | Description |
|---------|--------|-------------|
| `conversation_started` | `{ "type": "conversation_started", "session_id": "uuid" }` | Session initialized |
| `partial_transcript` | `{ "type": "partial_transcript", "text": "What is" }` | Interim STT result (every ~2 s) |
| `final_transcript` | `{ "type": "final_transcript", "text": "What is the weather" }` | Final STT after end-of-speech (filtered) |
| `assistant_stream` | `{ "type": "assistant_stream", "text": "The weather" }` | Streamed LLM response chunk |
| `assistant_done` | `{ "type": "assistant_done", "text": "full response" }` | LLM response complete (includes full text) |
| `tts_audio` | `{ "type": "tts_audio", "audio": "base64..." }` | TTS MP3 audio for playback |
| `tts_error` | `{ "type": "tts_error", "message": "..." }` | TTS generation failed |
| `latency` | `{ "type": "latency", "stt_ms": N, "llm_first_token_ms": N, "llm_total_ms": N, "tts_ms": N, "total_ms": N, "audio_duration_s": N }` | Per-stage pipeline latency metrics |
| `error` | `{ "type": "error", "message": "..." }` | Error notification |

---

## Example Conversation Flow

```
1.  User taps [Start Conversation]
2.  Client → Server:  { "type": "start_conversation" }
3.  Server → Client:  { "type": "conversation_started", "session_id": "abc-123" }
4.  Mic starts, AudioWorklet captures 16 kHz PCM
    2-second calibration phase (amber indicator, noise floor measured)

5.  User says: "What appointments are available tomorrow?"
    Sliding-window VAD confirms speech → pre-speech buffer flushed
    Client → Server:  [binary PCM chunks streamed while speech confirmed]

    ~2 s later:
    Server → Client:  { "type": "partial_transcript", "text": "What appointments" }

6.  User stops speaking (2 s silence detected by VAD)
    Client → Server:  { "type": "end_of_speech" }

7.  Server → Client:  { "type": "final_transcript",
                         "text": "What appointments are available tomorrow?" }

8.  Server calls Groq Llama 3 → tool call: check_available_slots("2026-03-06")
    → executes tool → feeds result back → streams final response

9.  Server → Client:  { "type": "assistant_stream", "text": "Here are the " }
    Server → Client:  { "type": "assistant_stream", "text": "available slots " }
    Server → Client:  { "type": "assistant_stream", "text": "for tomorrow..." }

10. Server → Client:  { "type": "assistant_done", "text": "Here are the available slots for tomorrow..." }

11. Server generates TTS audio (Deepgram Aura)
    Server → Client:  { "type": "tts_audio", "audio": "base64..." }

12. Frontend plays MP3 audio, words appear one-by-one in chat bubble (🔊 icon)
    Footer shows violet pulsing speaker icon with "Speaking…" label

13. (Optional) User speaks during TTS → barge-in detected
    Audio stops, text committed, system transitions to listening

14. TTS ends naturally → system resumes listening for next utterance.

15. User taps [Stop Conversation]
    Client → Server:  { "type": "stop_conversation" }
    WebSocket closes, mic stops.
```

---

## Database Schema

### patients
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Patient full name |
| `phone` | string | Primary phone (unique index) |
| `email` | string | Email address |
| `date_of_birth` | string | YYYY-MM-DD |
| `gender` | string | Gender |
| `address` | string | Postal address |
| `medical_history` | string | Notes |
| `allergies` | string[] | Known allergies |
| `emergency_contact` | {name, phone} | Emergency contact |
| `created_at` | datetime | Record creation |
| `updated_at` | datetime | Last update |

### dentists
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Dr. full name |
| `specialization` | string | General, Orthodontics, Endodontics, etc. |
| `phone` | string | Contact |
| `email` | string | Email |
| `available_days` | string[] | ["Monday", "Tuesday", …] |
| `working_hours` | {start, end} | e.g. {"start":"09:00","end":"17:00"} |

### dental_services
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Service name |
| `category` | string | Preventive, Restorative, Cosmetic, Surgical, etc. |
| `description` | string | Human-friendly description |
| `duration_minutes` | int | Typical duration |
| `price` | float | Price in USD |
| `is_active` | bool | Currently offered |

### appointments
| Field | Type | Description |
|-------|------|-------------|
| `patient_name` | string | Name |
| `patient_phone` | string | Phone |
| `date` | string | YYYY-MM-DD |
| `time` | string | e.g. "10:00 AM" |
| `service` | string | Service name |
| `dentist_name` | string | Optional |
| `status` | string | scheduled / completed / cancelled / no_show |
| `notes` | string | Additional notes |

### conversations
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | UUID (unique) |
| `started_at` | datetime | When started |
| `ended_at` | datetime | When ended |
| `status` | string | active / ended |

### chat_messages
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | References conversation |
| `role` | string | user / assistant |
| `content` | string | Message text |
| `message_type` | string | text / audio_transcript |

---

## Silence Detection (VAD) Implementation

The frontend uses **energy-based Voice Activity Detection** in the AudioWorklet:

1. **AudioWorklet Processor** (`audio-processor.js`):
   - Receives 128-sample blocks from the microphone
   - Calculates **RMS** (root mean square) of each block
   - Posts `{ type: 'vad', rms }` to the main thread

2. **Main Thread VAD Logic** (`App.jsx`):
   ```
   if RMS > THRESHOLD (0.008):
       → user is speaking
       → reset silence timer
   else if was_speaking AND no silence timer:
       → start 2.5 s countdown
       → if silence persists → send end_of_speech
   ```

3. **Tunables**:
   - `VAD_SILENCE_THRESHOLD = 0.008` — RMS below this = silence
   - `VAD_SILENCE_TIMEOUT_MS = 2500` — 2.5 s silence = end of speech
   - `VAD_SPEECH_MIN_MS = 500` — ignore ultra-short speech bursts

---

## How to Run Locally

### Prerequisites
- Python 3.11+
- Node.js 18+
- MongoDB running locally (or a cloud URI)

### Environment Variables (`.env`)
```env
MONGO_URI=mongodb://localhost:27017
GROQ_API_KEY=your-groq-api-key
DEEPGRAM_API_KEY=your-deepgram-api-key
# Optional (commented-out providers in code):
# GOOGLE_API_KEY=your-gemini-api-key
# ELEVEN_API_KEY=your-elevenlabs-api-key
```

### Backend
```bash
cd demo
python -m venv venv
source venv/Scripts/activate     # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** → click **Start Conversation** → speak.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, Tailwind CSS 4, AudioWorklet API, @vapi-ai/web |
| WebSocket | Native WebSocket (browser) ↔ FastAPI WebSocket |
| WebRTC | @vapi-ai/web SDK ↔ Vapi Cloud |
| Backend | FastAPI (Python), asyncio |
| STT | Deepgram Nova-3 (REST via httpx) |
| LLM | Groq Llama 3.3 70B Versatile (with JSON-schema function calling) |
| TTS | Deepgram Aura (aura-asteria-en, MP3) |
| Vapi | Vapi WebRTC (managed STT/LLM/TTS, tool webhook) |
| Database | MongoDB (pymongo) |
| Voice capture | Web Audio API → AudioWorklet → PCM-16 @ 16 kHz |

---

## Vapi WebRTC Architecture

SmileCare supports a second transport mode using **Vapi WebRTC**. In this mode, the entire voice pipeline (STT, LLM, TTS) runs in Vapi's cloud — only tool execution hits our backend via a webhook.

### Vapi Data Flow

```mermaid
graph TB
    subgraph Browser["Browser (React)"]
        TOGGLE["Mode Toggle<br/>WebSocket | Vapi"]
        VAPI_SDK["@vapi-ai/web SDK"]
        CHAT_UI["Chat Display + Debug"]
    end

    subgraph VapiCloud["Vapi Cloud"]
        WRT["WebRTC Endpoint"]
        V_STT["Deepgram Nova-2 STT"]
        V_LLM["Groq Llama 3.3 70B"]
        V_TTS["Deepgram Aura TTS"]
    end

    subgraph Backend["Our Backend (FastAPI)"]
        WEBHOOK["POST /vapi/webhook<br/>(vapi_webhook.py)"]
        TOOL_EXEC["Tool Handlers<br/>8 functions"]
        MONGO["MongoDB"]
    end

    TOGGLE --> VAPI_SDK
    VAPI_SDK <-->|"WebRTC<br/>audio + events"| WRT
    WRT --> V_STT --> V_LLM
    V_LLM -->|"function-call"| WEBHOOK
    WEBHOOK --> TOOL_EXEC --> MONGO
    MONGO --> TOOL_EXEC --> WEBHOOK
    WEBHOOK -->|"result"| V_LLM
    V_LLM --> V_TTS -->|"audio stream"| WRT
    WRT --> VAPI_SDK --> CHAT_UI

    style Browser fill:#e0f2fe,stroke:#0284c7
    style VapiCloud fill:#f3e8ff,stroke:#7c3aed
    style Backend fill:#f0fdf4,stroke:#16a34a
```

### Vapi Webhook

**Endpoint:** `POST /vapi/webhook`  
**File:** `app/routers/vapi_webhook.py`

When the LLM in Vapi's cloud triggers a tool call, Vapi sends a POST request to our webhook. The webhook:
1. Extracts `functionCall.name` and `functionCall.parameters`
2. Dispatches to the appropriate tool handler via `_execute_tool()`
3. Returns `{"result": "JSON string"}` to Vapi
4. Logs execution time with `[LATENCY][VAPI]` prefix

See `docs/VAPI_WEBRTC.md` for complete integration documentation.

---

## Latency Debug Architecture

### Server-Side Pipeline Measurement

The WebSocket handler in `main.py` measures latency at every stage with `[LATENCY]` log prefix:

```
[LATENCY][PIPELINE] ══════════════════════════════
[LATENCY][PIPELINE]  STT:     342 ms  (22%)  [wav=2ms + api=340ms]
[LATENCY][PIPELINE]  LLM:     920 ms  (60%)  [first_token=180ms, 8 chunks]
[LATENCY][PIPELINE]  TTS:     280 ms  (18%)  [18432 bytes MP3]
[LATENCY][PIPELINE]  TOTAL:  1542 ms  (audio captured: 2.1s)
[LATENCY][PIPELINE] ══════════════════════════════
```

### Sub-Stage Breakdown

| Stage | Sub-Stages |
|-------|-----------|
| **STT** | PCM→WAV conversion time + Deepgram API call time |
| **LLM** | First token time + total time + chunk count + history size |
| **TTS** | Generation time + MP3 byte size + text char count |

### Client-Side Round-Trip Measurement

The frontend independently times the journey using `performance.now()`:

| Metric | Start Event | End Event |
|--------|------------|-----------|
| STT round-trip | `end_of_speech` sent | `final_transcript` received |
| First LLM stream | `end_of_speech` sent | First `assistant_stream` received |
| Full round-trip | `end_of_speech` sent | `tts_audio` received |
| Network overhead | Computed: client round-trip − server pipeline |

### Debug Panel

The frontend debug panel shows both server and client metrics with color-coded thresholds, sub-stage detail rows, and running averages over the last 20 turns.

### Vapi Webhook Timing

Tool execution in Vapi mode is logged with `[LATENCY][VAPI]` prefix showing per-tool execution time.

See `docs/LATENCY_DEBUG.md` for a comprehensive guide on interpreting all metrics.
