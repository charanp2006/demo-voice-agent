# AI-Powered Dental Clinic Scheduling System

An intelligent AI assistant that handles appointment booking via voice and chat interactions. The system uses advanced language models with tool-calling capabilities to manage patient inquiries and appointments.

## Table of Contents

- [Overview](#overview)
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

## System Architecture

### Core Components

```mermaid
graph TD
    A["User<br/>(Voice/Chat)"]
    B["voice_service<br/>(Speech-to-Text)"]
    C["agent_service<br/>(AI Decision Making)"]
    D["llm_service<br/>(Intent Extraction)"]
    E["clinic router/service<br/>(Business Logic)"]
    F["Response<br/>(Confirmation)"]
    G["voice_service<br/>(Text-to-Speech)"]
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> A
```

### Tool-Based Agent Pattern

```mermaid
graph TD
    A["User Message"]
    B["agent_service"]
    C["LLM<br/>(with tools)"]
    D{"Tool Call<br/>Needed?"}
    E["Execute Python<br/>Function"]
    F["Return Result<br/>to User"]
    
    A --> B
    B --> C
    C --> D
    D -->|Yes| E
    D -->|No| F
    E --> F
```

---

## Request Flow

### REST API Workflow

```mermaid
graph TD
    A["Client Request<br/>POST /chat<br/>{message: ...}"]
    B["FastAPI Endpoint<br/>/chat"]
    C["Pydantic Validation<br/>ChatRequest"]
    D["process_message<br/>user_message"]
    E["Send to AI Model<br/>+ System Prompt<br/>+ Available Tools"]
    F{"AI Decision"}
    G["Skip Tools<br/>Respond Directly"]
    H["Generate Tool Call<br/>check_slots or<br/>book_appointment"]
    I["Execute Python<br/>Function"]
    J["Receive Result<br/>Python Dict"]
    K["Second Request to AI<br/>+ Original Message<br/>+ Tool Result"]
    L["AI Generates<br/>Natural Language Reply"]
    M["HTTP Response<br/>JSON"]
    N["Client Receives<br/>Response"]
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F -->|Direct Response| G
    F -->|Tool Needed| H
    G --> L
    H --> I
    I --> J
    J --> K
    K --> L
    L --> M
    M --> N
```

---

## Voice Processing

### Voice-Only Workflow

```mermaid
graph TD
    A["User Speaks"]
    B["Groq Whisper<br/>(Speech-to-Text)"]
    C["Gemini 2.5 Flash<br/>(Agent Logic)"]
    D["AI Decision"]
    E["FastAPI Executes<br/>Tool(s)"]
    F["Gemini Generates<br/>Response Text"]
    G["gTTS Converts<br/>to Speech"]
    H["Return Audio<br/>to User"]
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
```

---

## WebSocket Communication

For real-time, streaming interactions:

```mermaid
graph TB
    subgraph Client["Browser Client"]
        A1["Audio Chunks"]
        A2["STT Stream"]
        A3["TTS Stream"]
    end
    
    subgraph Server["FastAPI Server"]
        B1["Partial Transcript"]
        B2["LLM Stream"]
        B3["Audio Chunks"]
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