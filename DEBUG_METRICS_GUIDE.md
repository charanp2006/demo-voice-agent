# Debug Console & Metrics Guide

This document explains the debug console feature and all available metrics for troubleshooting the voice assistant application.

---

## Overview

The **Debug Console** is a collapsible panel in the frontend that provides real-time insights into the voice conversation system's performance and behavior.

### How to Use

1. The debug console appears at the bottom of the app (above the text input)
2. Click the header `🔧 Debug Console` to expand/collapse
3. All metrics update in real-time as you interact with the system
4. Starts fresh when you click "Start Conversation"

---

## Current Debug Metrics

### 1. ⏱️ Latency Metrics

Performance timings for each stage of the voice processing pipeline:

| Metric | Description | What It Measures | Optimal Range |
|--------|-------------|------------------|---------------|
| **STT** | Speech-To-Text latency | Time from audio sent to transcription received | 500-2000ms |
| **LLM** | Large Language Model latency | Time from transcription to agent response | 300-1500ms |
| **TTS** | Text-To-Speech latency | Time from agent response to audio ready | 800-3000ms |
| **Record** | Recording duration | How long you spoke (recording time) | User-dependent |
| **Network** | Network round-trip | Audio sent to first backend response | 200-1000ms |
| **Total** | End-to-end latency | Audio sent to audio ready to play | 2000-6000ms |

**How It's Calculated:**
```
User clicks mic → Recording starts (start time)
User clicks mic again → Recording stops (stop time)
Audio sent to server → audioSentTime
Transcription received → STT latency = transcriptionTime - audioSentTime
Agent text received → LLM latency = agentTextTime - transcriptionTime
Audio ready → TTS latency = audioReadyTime - agentTextTime
Total = audioReadyTime - audioSentTime
```

### 2. 🌐 Connection Metrics

WebSocket connection health:

| Metric | Description | Possible Values |
|--------|-------------|-----------------|
| **Socket** | WebSocket connection state | `open` (green), `closed` (red), `connecting` (yellow), `error` (red), `disconnected` |
| **Messages** | Number of WebSocket messages received | Increments with each event (transcription, agent_text, audio_ready, error, ack) |

### 3. 🎤 Audio Metrics

Information about the audio being processed:

| Metric | Description | Details |
|--------|-------------|---------|
| **Size** | Audio file size | Size of webm blob sent to server (in KB) |
| **Chunks** | Number of audio chunks | How many 1500ms chunks MediaRecorder captured |

### 4. 💬 Conversation Metrics

Session-level statistics:

| Metric | Description |
|--------|-------------|
| **Turns** | Total completed voice turns | Increments each time audio_ready is received |
| **Status** | Conversation state | `Active` (green) or `Inactive` (gray) |

### 5. 📋 Event Timeline

Last 6 WebSocket/system events in chronological order:

Examples:
- `conversation_started`
- `socket_open`
- `recording_started`
- `recording_stopped`
- `audio_sent`
- `transcription`
- `agent_text`
- `audio_ready`
- `socket_close`
- `reconnecting`
- `conversation_stopped`

### 6. ❌ Error Display

Shows the last error message received from backend or frontend processing:

- Only visible when an error has occurred
- Shows full error message text
- Highlighted in red for visibility

---

## Additional Metrics (Recommended for Future)

### High Priority

1. **CPU Usage**
   - Frontend rendering load
   - Helps identify performance bottlenecks
   - **Implementation**: Use `performance.now()` and measure frame times

2. **Memory Usage**
   - Browser memory consumption
   - Detect memory leaks in long conversations
   - **Implementation**: `performance.memory` API (Chrome only)

3. **Audio Quality Metrics**
   - Sample rate (e.g., 48kHz, 44.1kHz)
   - Bit rate
   - Number of channels (mono/stereo)
   - **Implementation**: Read from MediaRecorder stream settings

4. **Backend Response Size**
   - Size of transcription response
   - Size of agent text response
   - Size of TTS audio file
   - **Implementation**: Read `Content-Length` headers

5. **Jitter & Packet Loss**
   - Network stability indicator
   - WebSocket message timing variance
   - **Implementation**: Track message receive intervals

### Medium Priority

6. **Reconnection Stats**
   - Total reconnection attempts
   - Success/failure ratio
   - Average reconnection time
   - **Implementation**: Track reconnection events and timestamps

7. **Audio Buffer Status**
   - Recording buffer fullness
   - Playback buffer status
   - Detect audio glitches
   - **Implementation**: Monitor MediaRecorder state

8. **Processing Queue Depth**
   - Number of pending requests
   - Detect backend overload
   - **Implementation**: Track in-flight WebSocket messages

9. **Token/Character Counts**
   - Input tokens (transcription length)
   - Output tokens (agent response length)
   - Useful for cost analysis
   - **Implementation**: Count characters in messages

10. **Session Duration**
    - Time since conversation started
    - Uptime indicator
    - **Implementation**: `Date.now() - conversationStartTime`

### Nice to Have

11. **Rate Limiting Status**
    - API quota remaining
    - Requests per minute
    - **Implementation**: Backend header inspection

12. **STT Confidence Score**
    - How confident Whisper is in transcription
    - Lower score = might need re-recording
    - **Implementation**: Backend sends confidence from Groq API

13. **Voice Activity Detection (VAD)**
    - Detect silence vs speech
    - Auto-stop recording when user stops speaking
    - **Implementation**: Web Audio API analyser node

14. **Network Bandwidth**
    - Upload/download speed estimate
    - Predict latency issues
    - **Implementation**: Network Information API

15. **Geographic Latency**
    - Backend server location
    - User location
    - Ping time
    - **Implementation**: Backend sends server info

---

## Interpreting the Metrics

### Healthy System

```
STT: 800ms
LLM: 500ms
TTS: 1200ms
Total: 2500ms
Socket: open (green)
Chunks: 3
Size: 45.2 KB
```

### Slow Backend

```
STT: 3500ms ⚠️
LLM: 2800ms ⚠️
TTS: 4200ms ⚠️
Total: 10500ms ⚠️
```

**Diagnosis**: Backend overloaded or API rate limiting
**Solution**: Reduce concurrent requests, upgrade API plan, optimize backend

### Network Issues

```
Network: 3000ms ⚠️
Total: 8000ms ⚠️
Socket: connecting (yellow) → closed (red) → connecting (yellow)
Event Timeline: socket_close, reconnecting, socket_error, reconnecting
```

**Diagnosis**: Poor internet connection or backend unreachable
**Solution**: Check internet, verify backend is running, inspect firewall

### Audio Quality Issues

```
Size: 2.1 KB ⚠️ (too small)
Chunks: 1
Record: 300ms ⚠️ (too short)
```

**Diagnosis**: User didn't speak long enough or mic not working
**Solution**: Check microphone permissions, speak longer, check mic hardware

### Memory Leak

```
WebSocket Messages: 5847 ⚠️ (very high after long session)
Turns: 234
Total session: 45 minutes
```

**Diagnosis**: Possible memory leak or event listener not cleaned up
**Solution**: Stop and restart conversation, check browser DevTools memory profiler

---

## Technical Implementation Details

### State Management

All metrics are stored in React state:

```javascript
const [latencies, setLatencies] = useState({...});
const [debugMetrics, setDebugMetrics] = useState({...});
```

### Timestamp Tracking

Uses `useRef` for mutable timestamps without triggering re-renders:

```javascript
const audioSentTimeRef = useRef(null);
const transcriptionReceivedTimeRef = useRef(null);
// etc.
```

### Calculation Trigger

Latencies are calculated when `audio_ready` event is received (end of pipeline):

```javascript
if (data.type === 'audio_ready') {
  audioReadyReceivedTimeRef.current = Date.now();
  calculateLatencies(); // Computes all latencies
}
```

### WebSocket Event Tracking

Every WebSocket message increments the message counter and updates timeline:

```javascript
ws.onmessage = async (event) => {
  const data = JSON.parse(event.data);
  trackWsEvent(data.type); // Adds to timeline
  setDebugMetrics((prev) => ({ ...prev, wsMessageCount: prev.wsMessageCount + 1 }));
  // ... handle specific event types
};
```

---

## Troubleshooting with Debug Console

### Problem: "Audio is not being transcribed"

**Check:**
1. Socket status = `open`?
2. Audio Size > 0?
3. Chunks sent > 0?
4. Event timeline shows `audio_sent`?
5. Any errors in error display?

### Problem: "Responses are very slow"

**Check:**
1. Total latency > 5000ms?
2. Which component is slowest (STT/LLM/TTS)?
3. Network latency high?
4. Is backend responding at all (check timeline)?

### Problem: "Connection keeps dropping"

**Check:**
1. Event timeline shows repeated `socket_close`, `reconnecting`?
2. Socket state cycling between `connecting` and `closed`?
3. Network latency extremely high?
4. Backend logs show crashes?

### Problem: "Can't hear assistant response"

**Check:**
1. Did `audio_ready` event fire?
2. TTS latency shows a value (not `-`)?
3. Check browser audio is not muted
4. Check audio element in DevTools

---

## Best Practices

1. **Keep Debug Console Open During Development**
   - Helps catch issues immediately
   - Real-time feedback on performance

2. **Monitor Baselines**
   - Record typical latencies in your environment
   - Set alerts for anomalies

3. **Test Different Scenarios**
   - Long recordings (30+ seconds)
   - Short recordings (1-2 seconds)
   - Back-to-back turns (rapid-fire)
   - Network interruptions
   - Backend restarts

4. **Share Debug Screenshots**
   - When reporting bugs, include debug console screenshot
   - Helps maintainers diagnose issues faster

5. **Use Timeline for Flow Understanding**
   - Verify events happen in expected order:
     - `recording_started` → `recording_stopped` → `audio_sent` → `transcription` → `agent_text` → `audio_ready`

---

## Future Enhancements

- Export debug logs as JSON
- Historical metrics chart (latency over time)
- Alert thresholds (notify if latency > X ms)
- Comparison mode (current vs previous session)
- Integration with backend logging (correlate frontend metrics with backend logs)
