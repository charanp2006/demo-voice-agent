# Latency Debug Guide

SmileCare includes comprehensive latency measurement at every stage of the voice pipeline. This document explains how to read and interpret the debug output.

---

## Table of Contents

- [Overview](#overview)
- [Server-Side Latency (Backend Logs)](#server-side-latency-backend-logs)
- [Client-Side Latency (Debug Panel)](#client-side-latency-debug-panel)
- [Vapi Webhook Latency](#vapi-webhook-latency)
- [Interpreting the Numbers](#interpreting-the-numbers)
- [Optimization Targets](#optimization-targets)
- [Debug Panel Color Codes](#debug-panel-color-codes)

---

## Overview

Latency is measured at two levels:

1. **Server-side** (`app/main.py`): Granular per-stage timing with sub-stage breakdown, logged with `[LATENCY]` prefix
2. **Client-side** (`App.jsx`): Round-trip timing from the browser's perspective, shown in the debug panel

```
User speaks → VAD fires end_of_speech → Server receives
    ├── Stage 1: STT  (PCM→WAV + Deepgram API)
    ├── Stage 2: LLM  (Groq Llama 3.3 + tool calls)
    ├── Stage 3: TTS  (Deepgram Aura → MP3)
    └── Send tts_audio to client → Browser plays audio
```

---

## Server-Side Latency (Backend Logs)

### Log Prefix Convention

All latency-related logs use the `[LATENCY]` prefix for easy filtering:

```bash
# Filter latency logs in terminal
uvicorn app.main:app --reload 2>&1 | grep "[LATENCY]"
```

### Stage 1: STT (Speech-to-Text)

```
[LATENCY][STT] PCM→WAV: 2 ms (pcm=64000 bytes, wav=64044 bytes)
[LATENCY][STT] Deepgram API: 340 ms | Total STT: 342 ms | Result: 'what appointments are available tomorrow'
```

| Sub-Stage | Description |
|-----------|-------------|
| **PCM→WAV** | Time to wrap raw PCM-16 LE bytes in a WAV container (in-memory, typically <5 ms) |
| **Deepgram API** | Network round-trip to Deepgram Nova-3 for transcription |
| **Total STT** | Sum of the above |

### Stage 2: LLM (Language Model)

```
[LATENCY][LLM] Sending to Groq Llama 3.3: 'what appointments are available tomorrow' (history=2 msgs)
[LATENCY][LLM] First token: 180 ms
[LATENCY][LLM] Done — 142 chars, 8 chunks | First token: 180 ms | Total: 920 ms
```

| Metric | Description |
|--------|-------------|
| **First token** | Time from request to receiving the first streamed chunk (time-to-first-byte) |
| **Total** | Time for the complete LLM response (includes tool-calling rounds) |
| **Chunks** | Number of streamed text chunks received |
| **History** | Number of conversation history messages sent for context |

### Stage 3: TTS (Text-to-Speech)

```
[LATENCY][TTS] Generating Deepgram Aura audio (142 chars, ~28 words)
[LATENCY][TTS] Done — 18432 bytes MP3 | 280 ms | b64 payload: 24576 chars
```

| Metric | Description |
|--------|-------------|
| **Audio size** | Size of generated MP3 in bytes |
| **Time** | Network round-trip to Deepgram Aura API |
| **b64 payload** | Size of the base64-encoded audio sent over WebSocket |
| **Text chars/words** | Input text size (longer text → more generation time) |

### Pipeline Summary

After each turn, a summary block is logged:

```
[LATENCY][PIPELINE] ══════════════════════════════
[LATENCY][PIPELINE]  STT:     342 ms  (22%)  [wav=2ms + api=340ms]
[LATENCY][PIPELINE]  LLM:     920 ms  (60%)  [first_token=180ms, 8 chunks]
[LATENCY][PIPELINE]  TTS:     280 ms  (18%)  [18432 bytes MP3]
[LATENCY][PIPELINE]  TOTAL:  1542 ms  (audio captured: 2.1s)
[LATENCY][PIPELINE] ══════════════════════════════
```

This shows:
- Each stage's absolute time and percentage of total
- Sub-stage details in brackets
- Audio duration captured (for context — longer audio = larger STT payload)

---

## Client-Side Latency (Debug Panel)

The frontend debug panel (bottom-right toggle) shows two sections:

### Server Metrics (from `latency` WebSocket message)

The backend sends a `latency` message after each turn with all metrics. The debug panel displays:

| Row | Color Coding |
|-----|-------------|
| STT (Deepgram Nova-3) | Green <800ms, Yellow <1500ms, Red >1500ms |
| └ PCM→WAV | Gray (sub-stage detail) |
| └ API call | Gray (sub-stage detail) |
| LLM first token | Green <500ms, Yellow <1000ms, Red >1000ms |
| LLM total | Green <2000ms, Yellow <4000ms, Red >4000ms |
| └ Chunks | Gray (count) |
| TTS (Deepgram Aura) | Green <800ms, Yellow <1500ms, Red >1500ms |
| └ Audio size | Gray (KB) |
| **Total pipeline** | **Green <2000ms, Yellow <4000ms, Red >4000ms** |
| Audio captured | Gray (seconds) |

### Client Round-Trip (measured in browser)

The frontend independently times the journey from sending `end_of_speech` to receiving responses:

| Metric | What It Measures |
|--------|-----------------|
| **→ final_transcript** | `end_of_speech` sent → `final_transcript` received (STT + network) |
| **→ first LLM chunk** | `end_of_speech` sent → first `assistant_stream` received (STT + LLM TTFB + network) |
| **→ TTS audio** | `end_of_speech` sent → `tts_audio` received (full round-trip) |
| **Network overhead** | Client round-trip − server pipeline = WebSocket transport overhead |

### Debug Log Entries

Latency events in the debug log are prefixed with `⏱`:

```
[14:23:05] ⏱ CLIENT: end_of_speech → final_transcript: 380 ms (includes STT + network)
[14:23:05] ⏱ CLIENT: end_of_speech → first assistant_stream: 560 ms (STT + LLM first token + network)
[14:23:06] ⏱ CLIENT: end_of_speech → tts_audio: 1580 ms (full round-trip)
[14:23:06] ⏱ LATENCY — STT: 342ms [wav=2ms + api=340ms] | LLM: first=180ms total=920ms (8 chunks) | TTS: 280ms (18432 bytes) | Pipeline: 1542ms | Audio: 2.1s
[14:23:06] ⏱ CLIENT round-trip: 1580ms (overhead vs server: 38ms)
```

### Running Averages

The panel shows a running average over the last 20 turns at the bottom of the latency section. This helps identify trends vs one-off spikes.

---

## Vapi Webhook Latency

In Vapi WebRTC mode, the pipeline runs in Vapi's cloud. The only latency we can measure is tool execution:

```
[LATENCY][VAPI] function-call: check_available_slots({"date": "2026-03-06"})
[LATENCY][VAPI] check_available_slots completed in 12 ms (result: {"available_slots": ...})
```

This measures the time from receiving the webhook POST to returning the result. It includes:
- JSON parsing
- Tool dispatch
- MongoDB query
- Result serialization

Vapi's `end-of-call-report` event (logged in the debug panel) provides total call duration and cost.

---

## Interpreting the Numbers

### Typical Healthy Values (Local Development)

| Stage | Expected | Notes |
|-------|----------|-------|
| PCM→WAV | <5 ms | In-memory conversion, CPU-bound |
| STT API (Deepgram Nova-3) | 200–600 ms | Depends on audio length and network |
| LLM first token (Groq) | 100–400 ms | Groq is fast; tool calls add rounds |
| LLM total | 400–2000 ms | Depends on response length and tool calls |
| TTS (Deepgram Aura) | 150–500 ms | Depends on text length |
| **Total pipeline** | **1000–3000 ms** | **Under 2s is "good" for voice** |
| Network overhead | 10–50 ms | Local dev; production may be higher |

### What Affects Latency

| Factor | Impact |
|--------|--------|
| Audio duration | Longer audio → larger STT payload → higher STT time |
| Response length | More words → more LLM chunks → more TTS generation time |
| Tool calls | Each tool-calling round adds ~200–400 ms (LLM → tool → LLM) |
| Network distance | STT/TTS API calls go to Deepgram servers; Groq goes to Groq servers |
| Cold start | First request may be slower (connection pooling, model warm-up) |

---

## Optimization Targets

| Priority | Target | Strategy |
|----------|--------|----------|
| 1 | LLM first token <300ms | Groq is already fast; keep system prompt concise |
| 2 | STT total <500ms | Deepgram Nova-3 is fast; reduce audio buffer size if possible |
| 3 | TTS total <400ms | Deepgram Aura is fast; keep responses short for voice |
| 4 | Total <2000ms | Optimize the bottleneck stage (usually LLM with tool calls) |
| 5 | Client overhead <50ms | Use localhost or low-latency hosting |

---

## Debug Panel Color Codes

### Latency Values

| Color | Meaning |
|-------|---------|
| 🟢 Green (`text-emerald-400`) | Fast — within target |
| 🟡 Yellow (`text-yellow-400`) | Moderate — acceptable but could improve |
| 🔴 Red (`text-red-400`) | Slow — needs investigation |

### Debug Log Entries

| Color | Meaning |
|-------|---------|
| 🟢 Green (`text-emerald-400`) | Success events (speech confirmed, call done) |
| 🔴 Red (`text-red-400`) | Errors, rejections, warnings |
| 🔵 Cyan (`text-cyan-400`) | Latency measurements |
| ⚪ Default green (`text-green-400`) | General debug events |
