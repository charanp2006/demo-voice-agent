# AI-Powered Dental Clinic Scheduling System

An intelligent AI assistant that handles appointment booking via voice and chat interactions. The system uses advanced language models with tool-calling capabilities to manage patient inquiries and appointments.

## Table of Contents

- [Overview](#overview)
- [Complete Application Flow](#complete-application-flow)
- [System Architecture](#system-architecture)
- [Request Flow](#request-flow)
- [Voice Processing](#voice-processing)
- [WebSocket Communication](#websocket-communication)
- [Project Structure](#project-structure)
- [Future Enhancements](#future-enhancements)

---

## Overview

This application provides a conversational AI interface for a dental clinic that handles:
- **Appointment booking** through natural language conversation
- **Slot availability checking** for requested dates
- **Voice-based interactions** with speech-to-text and text-to-speech
- **Multi-channel communication** via REST API and WebSocket

---

## Complete Application Flow

### End-to-End Sequence Diagram

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI /chat
    participant Agent as agent_service
    participant LLM as llm_service
    participant Clinic as clinic_service
    participant Voice as voice_service

    Note over U,Voice: Chat-Based Appointment Booking
    U->>API: POST /chat {message: "Book appointment tomorrow at 3pm"}
    API->>Agent: process_message(message)
    Agent->>LLM: send_to_llm(message, tools)
    LLM->>LLM: Analyze intent + available tools
    
    alt Tool Call Required
        LLM->>Agent: tool_call: check_slots(date="2026-03-04")
        Agent->>Clinic: check_slots(date)
        Clinic-->>Agent: {available_slots: ["9am", "3pm", "5pm"]}
        Agent->>LLM: Send tool result
        LLM->>Agent: tool_call: book_appointment({...})
        Agent->>Clinic: book_appointment(name, phone, date, time)
        Clinic-->>Agent: {success: true, appointment_id: 123}
        Agent->>LLM: Send booking result
        LLM-->>Agent: "Your appointment is confirmed for March 4 at 3pm"
    else Direct Response
        LLM-->>Agent: Direct answer (no tools needed)
    end
    
    Agent-->>API: {response: "..."}
    API-->>U: JSON Response

    Note over U,Voice: Voice-Based Interaction
    U->>Voice: Audio input (speech)
    Voice->>Voice: Groq Whisper (STT)
    Voice->>Agent: Transcribed text
    Agent->>LLM: Process with tools
    LLM->>Clinic: Execute tool functions
    Clinic-->>LLM: Return results
    LLM-->>Agent: Natural language response
    Agent->>Voice: Response text
    Voice->>Voice: gTTS (TTS)
    Voice-->>U: Audio output
```

---

## System Architecture

### Core Components

```mermaid
graph LR
    A["User<br/>(Voice/Chat)"]
    B["voice_service<br/>(Speech-to-Text)"]
    C["agent_service<br/>(AI Decision Making)"]
    D["llm_service<br/>(Intent Extraction)"]
    E["clinic router/service<br/>(Business Logic)"]
    F["Response<br/>(Confirmation)"]
    G["voice_service<br/>(Text-to-Speech)"]
    
    A --> B --> C --> D --> E --> F --> G --> A
```

### Tool-Based Agent Pattern

```mermaid
graph LR
    A["User Message"]
    B["agent_service"]
    C["LLM<br/>(with tools)"]
    D{"Tool Call<br/>Needed?"}
    E["Execute Python<br/>Function"]
    F["Return Result<br/>to User"]
    
    A --> B --> C --> D
    D -->|Yes| E --> F
    D -->|No| F
```

---

## Request Flow

### REST API Workflow

```mermaid
graph LR
    A["Client Request<br/>POST /chat"]
    B["FastAPI<br/>Endpoint"]
    C["Pydantic<br/>Validation"]
    D["process_<br/>message"]
    E["Send to AI<br/>+ Tools"]
    F{"AI<br/>Decision"}
    G["Direct<br/>Response"]
    H["Tool<br/>Call"]
    I["Execute<br/>Function"]
    J["Result<br/>Dict"]
    K["Second<br/>AI Call"]
    L["Final<br/>Reply"]
    M["HTTP<br/>Response"]
    
    A --> B --> C --> D --> E --> F
    F -->|Direct| G --> L
    F -->|Tool| H --> I --> J --> K --> L
    L --> M
```

---

## Voice Processing

### Voice-Only Workflow

```mermaid
graph LR
    A["User<br/>Speaks"]
    B["Groq Whisper<br/>(STT)"]
    C["Gemini 2.5<br/>(Agent Logic)"]
    D["FastAPI<br/>Execute Tools"]
    E["Gemini<br/>Response"]
    F["gTTS<br/>(TTS)"]
    G["Audio<br/>Output"]
    
    A --> B --> C --> D --> E --> F --> G
```

---

## WebSocket Communication

For real-time, streaming interactions:

```mermaid
graph LR
    subgraph Client["Browser Client"]
        A1["Audio<br/>Chunks"]
        A2["STT<br/>Stream"]
        A3["TTS<br/>Stream"]
    end
    
    subgraph Server["FastAPI Server"]
        B1["Partial<br/>Transcript"]
        B2["LLM<br/>Stream"]
        B3["Audio<br/>Chunks"]
    end
    
    A1 <-->|WebSocket| B1
    A2 <-->|WebSocket| B2
    A3 <-->|WebSocket| B3
```

---

## Project Structure

```
demo/
├── Readme.md                 # Project documentation
├── requirements.txt          # Python dependencies
└── app/
    ├── __init__.py
    ├── main.py              # FastAPI application entry point
    ├── models/
    │   ├── __init__.py
    │   └── schema.py        # Pydantic request/response schemas
    ├── routers/
    │   ├── __init__.py
    │   └── clinic.py        # Appointment booking endpoints
    └── services/
        ├── __init__.py
        ├── agent_service.py # AI agent orchestration
        ├── llm_service.py   # LLM interactions & tool calling
        └── voice_service.py # Speech-to-text & text-to-speech
```

---

## Future Enhancements

- **User Authentication**: Register users in the system for persistent profiles
- **Confirmations**: Send SMS/Email/in-app notifications after appointment booking
- **Appointment Management**: Allow users to reschedule or cancel appointments
- **Multi-language Support**: Extend voice processing to support multiple languages
- **Analytics Dashboard**: Track bookings, common queries, and system performance
- **Calendar Integration**: Sync with clinic management systems
- **Appointment Reminders**: Automated reminders via SMS/email before appointments