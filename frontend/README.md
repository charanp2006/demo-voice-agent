# SmileCare – Frontend

React 18 voice-first frontend for the SmileCare Dental Clinic AI assistant. Uses the **AudioWorklet API** for low-latency microphone capture, client-side **energy-based VAD** for automatic speech boundary detection, and a persistent **WebSocket** to stream audio and receive AI responses in real time.

---

## Table of Contents

- [Architecture](#architecture)
- [Audio Pipeline](#audio-pipeline)
- [VAD (Voice Activity Detection)](#vad-voice-activity-detection)
- [WebSocket Client Protocol](#websocket-client-protocol)
- [UI Components](#ui-components)
- [State Management](#state-management)
- [File Structure](#file-structure)
- [Development](#development)
- [Configuration](#configuration)

---

## Architecture

```mermaid
graph LR
  subgraph Browser
    MIC["��� getUserMedia<br/>48 kHz"]
    CTX["AudioContext<br/>(48 kHz)"]
    WK["AudioWorkletNode<br/>audio-capture-processor"]
    VAD["VAD State Machine<br/>(main thread)"]
    WS["WebSocket Client"]
    UI["React Chat UI<br/>(streaming bubbles)"]
  end

  subgraph Backend
    SRV["FastAPI /ws/voice"]
  end

  MIC --> CTX --> WK
  WK -->|"{type:'audio', buffer}"| VAD
  WK -->|"{type:'vad', rms}"| VAD
  VAD -->|"Binary PCM-16 LE"| WS
  VAD -->|"JSON control messages"| WS
  WS <-->|"WebSocket"| SRV
  SRV -->|"JSON messages"| UI
```

### Two-button Interface

The UI has only **two controls**: **Start Conversation** and **Stop Conversation**. There is no separate mic toggle, no text input, and no debug panel. Speech boundaries are detected automatically by the VAD.

---

## Audio Pipeline

```mermaid
flowchart TD
  A["Microphone (48 kHz)"] --> B["AudioContext"]
  B --> C["MediaStreamSource"]
  C --> D["AudioWorkletNode<br/>(audio-capture-processor)"]
  D -->|"process() every 128 frames"| E{"Downsample<br/>48 kHz → 16 kHz"}
  E --> F["Accumulate 1024 samples<br/>(≈ 64 ms at 16 kHz)"]
  F -->|"postMessage({type:'audio'})"| G["Main Thread"]
  G --> H["float32ToInt16Bytes()"]
  H --> I["ws.send(ArrayBuffer)<br/>Binary WebSocket frame"]

  D -->|"RMS on full-rate data"| J["postMessage({type:'vad', rms})"]
  J --> K["Main Thread VAD Logic"]
```

### AudioWorklet Processor (`audio-processor.js`)

The worklet runs in a dedicated audio thread to avoid main-thread jank:

| Property | Value | Description |
|----------|-------|-------------|
| Target sample rate | 16 kHz | Downsampled from native rate via decimation |
| Chunk size | 1024 samples | ≈ 64 ms of audio per message |
| RMS computation | Every `process()` call | Computed on original full-rate samples |
| Decimation method | Simple skip (every Nth sample) | `ratio = round(sourceRate / targetRate)` |

The processor posts two message types to the main thread:
- `{type: 'audio', buffer: Float32Array}` — downsampled audio chunk
- `{type: 'vad', rms: number}` — energy level for voice activity detection

---

## VAD (Voice Activity Detection)

Client-side energy-based VAD runs entirely in the main thread using RMS values from the AudioWorklet:

```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> Speaking : RMS > 0.008
  Speaking --> Speaking : RMS > 0.008<br/>(reset timer)
  Speaking --> SilenceWait : RMS ≤ 0.008
  SilenceWait --> Speaking : RMS > 0.008<br/>(cancel timer)
  SilenceWait --> EndOfSpeech : 2500 ms elapsed &<br/>speech ≥ 500 ms
  EndOfSpeech --> Idle : send end_of_speech
```

### Parameters

| Constant | Value | Purpose |
|----------|-------|---------|
| `VAD_SILENCE_THRESHOLD` | `0.008` | RMS below this counts as silence |
| `VAD_SILENCE_TIMEOUT_MS` | `2500` | Milliseconds of continuous silence to end turn |
| `VAD_SPEECH_MIN_MS` | `500` | Minimum speech duration before silence is respected |

### How it works

1. AudioWorklet posts `{type: 'vad', rms}` on every `process()` call (~5.3 ms at 48 kHz)
2. If `rms > 0.008` → mark speech started, clear any silence timer
3. If `rms ≤ 0.008` and speech is active → start a 2500 ms `setTimeout`
4. If the timer fires and total speech was ≥ 500 ms → send `{"type": "end_of_speech"}` to the server
5. If RMS rises again before the timer fires → cancel the timer and continue listening

---

## WebSocket Client Protocol

```mermaid
sequenceDiagram
  participant App as React App
  participant WS as WebSocket
  participant Server as FastAPI

  App->>WS: new WebSocket(ws://localhost:8000/ws/voice)
  WS->>Server: Connection opened

  App->>Server: {"type": "start_conversation"}
  Server->>App: {"type": "conversation_started", "session_id": "uuid"}

  loop User speaking
    App->>Server: Binary (PCM-16 LE ArrayBuffer)
  end

  Note over Server: Periodic partial STT
  Server-->>App: {"type": "partial_transcript", "text": "..."}

  Note over App: VAD fires end_of_speech
  App->>Server: {"type": "end_of_speech"}
  Server->>App: {"type": "final_transcript", "text": "full text"}

  loop Streamed response
    Server->>App: {"type": "assistant_stream", "text": "chunk"}
  end
  Server->>App: {"type": "assistant_done"}

  App->>Server: {"type": "stop_conversation"}
  Note over WS: Connection closed
```

### Message handling in `App.jsx`

| Server message | UI action |
|---------------|-----------|
| `conversation_started` | Store `session_id` |
| `partial_transcript` | Show italic user text with ▎ cursor |
| `final_transcript` | Commit user bubble to message list |
| `assistant_stream` | Append to green streaming bubble with ▎ cursor |
| `assistant_done` | Commit assistant bubble, reset to "Listening…" |
| `error` | Flash error status for 3 s, then resume |

---

## UI Components

The entire frontend is a single `App.jsx` component with these visual sections:

### Header
- App title: **��� SmileCare AI**
- Status text (Connecting / Listening / Processing / Error)
- Start or Stop button (toggles based on `conversationActive`)

### Chat Area
- **User bubbles** (blue, right-aligned) — committed `final_transcript` messages
- **Partial transcript** (lighter blue, italic, right-aligned) — live interim STT
- **Assistant bubbles** (white with border, left-aligned) — committed responses
- **Streaming bubble** (green border, left-aligned) — live `assistant_stream` with typing cursor
- **Thinking indicator** — bouncing dots shown during processing before stream starts
- Auto-scrolls to latest message

### Footer (visible during active conversation)
- **Audio level ring** — circular indicator that scales with RMS energy
- Microphone icon with dynamic color (green when speaking, gray when idle)
- Status label: Listening / Processing / Waiting for speech

---

## State Management

All state is managed with React hooks (`useState`, `useRef`, `useCallback`):

| State | Type | Purpose |
|-------|------|---------|
| `conversationActive` | `boolean` | Whether a session is in progress |
| `status` | `string` | Status bar text |
| `userText` | `string` | Live partial transcript |
| `assistantText` | `string` | Live streaming assistant text |
| `messages` | `{role, content}[]` | Committed chat history |
| `isSpeaking` | `boolean` | VAD detected active speech |
| `isProcessing` | `boolean` | Waiting for / receiving assistant response |
| `sessionId` | `string` | Current WebSocket session ID |
| `rmsLevel` | `number` | Current audio energy level |

### Refs

| Ref | Purpose |
|-----|---------|
| `wsRef` | WebSocket instance |
| `audioCtxRef` | AudioContext instance |
| `workletNodeRef` | AudioWorkletNode |
| `streamRef` | MediaStream (for cleanup) |
| `silenceTimerRef` | VAD silence timeout ID |
| `speechStartRef` | Timestamp of speech onset |
| `hasSpeechRef` | Whether VAD has detected speech |
| `activeRef` | Non-stale active flag for closures |
| `assistantBuf` | Accumulates streamed assistant chunks |
| `chatEndRef` | Scroll-to-bottom anchor |

---

## File Structure

```
frontend/
├── index.html               # Root HTML (mounts #root)
├── package.json              # React 18, Vite, Tailwind CSS 4
├── vite.config.js            # Vite config with React + Tailwind plugins
├── public/
│   └── audio-processor.js    # AudioWorklet processor (16 kHz + RMS)
└── src/
    ├── main.jsx              # React root render
    ├── App.jsx               # Full voice UI (361 lines)
    └── index.css             # Tailwind CSS imports
```

---

## Development

### Prerequisites

- Node.js 18+
- Backend running at `http://localhost:8000`

### Install & run

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. The Vite dev server proxies nothing — the React app connects directly to the FastAPI backend via WebSocket (`ws://localhost:8000/ws/voice`).

### Build for production

```bash
npm run build
npm run preview
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE` | `http://localhost:8000` | Backend URL (auto-derives WS URL) |

Set via `.env` in the `frontend/` directory:

```env
VITE_API_BASE=http://localhost:8000
```

The WebSocket URL is derived automatically by replacing `http` with `ws`:

```js
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const WS_BASE  = API_BASE.replace(/^http/i, 'ws');
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | ^18.3.1 | UI framework |
| `react-dom` | ^18.3.1 | React DOM renderer |
| `tailwindcss` | ^4.2.1 | Utility-first CSS |
| `@tailwindcss/vite` | ^4.2.1 | Tailwind Vite integration |
| `lucide-react` | ^0.576.0 | Icon library |
| `vite` | ^5.4.19 | Build tool |
| `@vitejs/plugin-react` | ^4.6.0 | React fast refresh |
