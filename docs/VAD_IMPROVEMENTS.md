# Voice Activity Detection (VAD) & Audio Pipeline — Improvements

## Problem

The original RMS-based VAD used a **fixed threshold** (`0.008`) to distinguish speech from silence. This caused false positives from:

- Laptop fan noise
- Air conditioning hum
- Keyboard typing / scraping sounds
- Objects falling or bumping
- Whispering / breathing
- Random environmental noise spikes
- Whisper STT hallucinations ("thank you for watching") on silence

Additionally, the original system had no Text-to-Speech (TTS) playback — the assistant only responded with text. When TTS was added, the assistant's own audio would trigger the VAD, creating echo-loop false positives.

## Solution Overview

The improved system uses **ten layered defenses** across frontend and backend, plus a full TTS pipeline with barge-in support:

| Layer | Mechanism | Where |
|-------|-----------|-------|
| 1 | Dynamic noise-floor calibration (×6) | `App.jsx` — calibration phase |
| 2 | Hard minimum absolute threshold (0.02) | `App.jsx` — `MIN_ABSOLUTE_THRESHOLD` |
| 3 | RMS smoothing (EMA, α=0.35) | `App.jsx` — `RMS_SMOOTHING_ALPHA` |
| 4 | Crest-factor impulsive-noise rejection (>10) | `App.jsx` — `MAX_CREST_FACTOR` |
| 5 | Sliding-window ratio-based speech confirmation | `App.jsx` — `SPEECH_WINDOW_MS` / `SPEECH_RATIO` |
| 6 | Pre-speech ring buffer (3.8 s look-back) | `App.jsx` — `PRE_SPEECH_CHUNKS` |
| 7 | Audio gating — only send PCM when speech confirmed | `App.jsx` — audio handler |
| 8 | STT hallucination blocklist (frontend) | `App.jsx` — `HALLUCINATION_PATTERNS` |
| 9 | STT hallucination blocklist (backend) | `main.py` — `_is_valid_transcript()` |
| 10 | TTS echo suppression via elevated threshold (×2.5) | `App.jsx` — `TTS_INTERRUPT_MULTIPLIER` |

---

## 1. Dynamic Noise-Floor Calibration

### How it works

When the user starts a conversation, the system enters a **2-second calibration phase**. During this window:

1. The AudioWorklet posts RMS values every ~2.7 ms (128 samples at 48 kHz).
2. The main thread collects all raw RMS samples.
3. After 2 seconds the **average RMS** is the **noise floor**.
4. The speech threshold is:

```
threshold = max(noise_floor × 6, 0.02)
```

### Why ×6 multiplier?

A 6× multiplier requires speech to have **six times the energy** of the ambient background. This cleanly rejects:

- Fan noise (RMS ≈ 0.002–0.005) → threshold 0.012–0.030
- Keyboard / scraping (RMS ≈ 0.005–0.015) → below threshold
- Normal speech (RMS ≈ 0.03–0.15) → easily passes

| Constant | Default | Description |
|----------|---------|-------------|
| `CALIBRATION_DURATION_MS` | `2000` | Calibration window |
| `NOISE_FLOOR_MULTIPLIER` | `6` | Threshold = noise_floor × this |
| `MIN_ABSOLUTE_THRESHOLD` | `0.02` | Hard minimum threshold |

---

## 2. RMS Smoothing (Exponential Moving Average)

Raw per-frame RMS is noisy — a single loud sample can spike it. We apply an **exponential moving average**:

```
smoothed = α × raw + (1 - α) × prev_smoothed
```

With `α = 0.35`, transient spikes are absorbed over several frames while speech (which sustains for hundreds of milliseconds) still rises through.

| Constant | Default | Description |
|----------|---------|-------------|
| `RMS_SMOOTHING_ALPHA` | `0.35` | 0 = heavy smoothing, 1 = raw passthrough |

---

## 3. Crest-Factor Impulsive Noise Rejection

**Crest factor** = `peak / RMS`. It measures how "spiky" an audio frame is.

| Sound type | Typical crest factor |
|-----------|---------------------|
| Speech | 3–6 |
| Keyboard click | 10–30 |
| Object drop | 15–50 |
| Clap | 12–25 |

Any frame with **crest factor > 10** is classified as an impulsive transient and rejected, regardless of RMS level. This is the key defense against keyboard typing, scraping, and objects falling.

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_CREST_FACTOR` | `10` | Above this = impulsive, not speech |

---

## 4. Sliding-Window Ratio-Based Speech Confirmation

Instead of requiring **continuous** above-threshold frames (which fails on natural speech with micro-pauses between syllables), the VAD uses a **sliding window** approach:

1. Each VAD frame is recorded as `{timestamp, above: true/false}` in a history buffer.
2. The buffer is trimmed to the last `SPEECH_WINDOW_MS` (400 ms).
3. If ≥ `SPEECH_RATIO` (50%) of frames in the window are above threshold → **speech detected**.
4. Speech is confirmed immediately once the sliding window agrees.

This tolerates natural speech patterns — plosive consonants with brief silences, pauses at commas, and varying syllable energy.

```
Window: [above, below, above, above, below, above, above, above]
Ratio:  6/8 = 0.75 ≥ 0.5 → SPEECH CONFIRMED ✓
```

| Constant | Default | Description |
|----------|---------|-------------|
| `SPEECH_WINDOW_MS` | `400` | Sliding window length |
| `SPEECH_RATIO` | `0.5` | Minimum fraction of above-threshold frames |

---

## 5. Pre-Speech Ring Buffer

To prevent truncating the start of an utterance (the first words spoken before the confirmation gate fires), the frontend maintains a **ring buffer** of recent audio chunks:

- Stores up to `PRE_SPEECH_CHUNKS` (15) audio chunks ≈ 3.8 seconds of look-back
- When speech is confirmed, the entire buffer is flushed to the backend before live audio
- After flushing, the buffer is cleared; new chunks go directly to the WebSocket

| Constant | Default | Description |
|----------|---------|-------------|
| `PRE_SPEECH_CHUNKS` | `15` | Number of ~256 ms audio chunks to buffer |

---

## 6. Audio Gating — No Audio Sent Until Speech Confirmed

**This is the single most important change.** Previously, ALL audio after calibration was streamed to the backend. Whisper received minutes of fan noise and hallucinated phrases like "thank you for watching".

Now: **PCM audio is only sent to the WebSocket when `speechConfirmedRef` is true.** The backend receives zero bytes of noise, so Whisper has nothing to hallucinate on.

---

## 7. Silence Detection

Once speech is confirmed, **2 seconds** of below-threshold RMS triggers `end_of_speech`. If total speech duration is under 600 ms, it's discarded as a false positive.

| Constant | Default | Description |
|----------|---------|-------------|
| `VAD_SILENCE_TIMEOUT_MS` | `2000` | Silence before end-of-speech |
| `VAD_SPEECH_MIN_MS` | `600` | Minimum total speech to be valid |

---

## 8. STT Hallucination Blocklist

Both **frontend** and **backend** independently filter transcripts against known Whisper hallucination patterns:

| Pattern | Catches |
|---------|---------|
| `thank(s\| you) for watching/listening` | Most common Whisper hallucination |
| `like/subscribe` | YouTube-trained hallucination |
| `[Music]`, `(upbeat music)` | Non-speech annotations |
| `um`, `uh`, `hmm`, `ah` (alone) | Filler-only transcripts |
| `you` (alone), `bye` (alone) | Single-word noise artefacts |
| Just dots / ellipsis | Empty-ish output |

**Frontend**: `HALLUCINATION_PATTERNS` array in `App.jsx` — checked on `final_transcript`.
**Backend**: `_is_valid_transcript()` in `main.py` — checked on both partial and final transcription.

Transcripts must also pass minimum length: **≥ 2 words** and **≥ 4 characters**.

---

## 9. TTS Echo Suppression & Barge-In

When the assistant speaks via TTS, the microphone picks up the audio output (echo). To prevent this from triggering the VAD while still allowing the user to interrupt (barge-in):

- The VAD **stays active** during TTS playback (not fully suppressed).
- The speech threshold is **raised by ×2.5** (`TTS_INTERRUPT_MULTIPLIER`) during TTS.
- The user must speak **significantly louder than the playback** to trigger speech detection.
- When speech is confirmed during TTS, `stopTTS()` is called:
  - Audio playback is paused immediately
  - The word-reveal timer is stopped
  - The full assistant text is committed to chat history
  - The mic transitions to normal listening mode with the standard threshold

| Constant | Default | Description |
|----------|---------|-------------|
| `TTS_INTERRUPT_MULTIPLIER` | `2.5` | Threshold multiplier during TTS playback |

---

## TTS (Text-to-Speech) Pipeline

### Architecture

```
LLM streaming response → assistant_done (with full text)
  → Backend: ElevenLabs TTS (or gTTS fallback)
  → Base64-encoded MP3 sent via WebSocket (tts_audio message)
  → Frontend: Decode → HTMLAudioElement.play()
  → Word-by-word text reveal timed to audio duration
  → On playback end: commit message to chat, resume listening
```

### Word-by-Word Reveal

The assistant response appears word-by-word in a chat bubble, synchronized with the TTS audio:

1. `assistant_stream` chunks are silently buffered (not shown to the user).
2. `assistant_done` stores the full text and waits for `tts_audio`.
3. When `tts_audio` arrives, the frontend decodes the base64 MP3 audio.
4. On `loadedmetadata`, it calculates `interval = duration / wordCount`.
5. A `setInterval` reveals one word at a time, matching the speaking pace.
6. A 🔊 icon appears in the chat bubble during playback.
7. On `audio.onended`, the full text is committed to the message history and the system returns to listening.

### Fallback Behavior

- If TTS generation fails on the server → `tts_error` is sent → text is shown immediately without audio.
- If `audio.play()` is blocked (autoplay policy) → text is shown immediately.
- If audio playback errors → text is shown immediately.

### WebSocket Messages (TTS)

| Direction | `type` | Payload | Description |
|-----------|--------|---------|-------------|
| Server → Client | `assistant_done` | `text` | Full response text (triggers TTS wait) |
| Server → Client | `tts_audio` | `audio` (base64) | MP3 audio bytes |
| Server → Client | `tts_error` | `message` | TTS generation failed |

---

## Audio Pipeline (Complete)

```
Microphone
  → getUserMedia (echoCancellation + noiseSuppression enabled)
  → AudioContext (48 kHz)
  → AudioWorkletNode (audio-capture-processor)
       ├─ posts { type: "vad", rms, peak } every ~2.7 ms
       └─ posts { type: "audio", buffer } every ~256 ms
  → Main thread VAD logic
       ├─ Phase 1: Calibration (2 s) — collects RMS, computes threshold
       └─ Phase 2: Speech detection (sliding-window ratio)
            ├─ RMS smoothing (EMA, α=0.35)
            ├─ Crest-factor check (reject if > 10)
            ├─ Sliding-window ratio (50% of 400 ms)
            ├─ Pre-speech buffer (15 chunks ≈ 3.8 s)
            ├─ Audio gate (only send PCM when confirmed)
            ├─ TTS echo suppression (threshold × 2.5 during playback)
            └─ Silence timer → end_of_speech
  → WebSocket → backend Whisper STT
       ├─ Server-side hallucination filter
       └─ final_transcript → LLM → assistant response
  → Backend TTS (ElevenLabs / gTTS)
       └─ tts_audio → Frontend playback + word-by-word reveal

User barge-in during TTS:
  → VAD detects speech (elevated threshold passes)
  → stopTTS() pauses audio, commits text
  → Normal listening resumes with pre-speech buffer
```

---

## Debug Panel

A collapsible debug panel is available at the bottom-right of the UI:

- Toggle with **▲ Show Debug / ▼ Hide Debug**
- Shows timestamped VAD events: calibration, speech confirmed, silence detected, end-of-speech
- Shows transcript events: partial, final, rejections, hallucination filtering
- Shows TTS events: audio received, playback started/ended, interrupts
- Color-coded: red for errors/rejections, green for confirmations
- Also logs to browser console with `[VAD-DBG]` prefix

---

## Tuning Guide

### Still getting false triggers?

1. **Increase `NOISE_FLOOR_MULTIPLIER`** from 6 → 8 or 10.
2. **Increase `MIN_ABSOLUTE_THRESHOLD`** from 0.02 → 0.03.
3. **Decrease `SPEECH_RATIO`** — wait, that makes it easier. Instead **increase `SPEECH_RATIO`** to 0.6 or 0.7.
4. **Increase `SPEECH_WINDOW_MS`** from 400 → 600 (longer observation window).
5. **Decrease `MAX_CREST_FACTOR`** from 10 → 8 (rejects more transients).
6. **Decrease `RMS_SMOOTHING_ALPHA`** from 0.35 → 0.2 (heavier smoothing).

### Legitimate speech being missed?

1. **Decrease `NOISE_FLOOR_MULTIPLIER`** to 4.
2. **Decrease `SPEECH_RATIO`** to 0.3–0.4.
3. **Decrease `SPEECH_WINDOW_MS`** to 250–300.
4. **Increase `MAX_CREST_FACTOR`** to 12–15.
5. Ensure the room is **quiet during the 2-second calibration** — the noise floor must reflect actual ambient levels.

### TTS being interrupted too easily?

1. **Increase `TTS_INTERRUPT_MULTIPLIER`** from 2.5 → 3.5 or 4.

### User can't interrupt TTS?

1. **Decrease `TTS_INTERRUPT_MULTIPLIER`** to 1.5–2.0.

---

## Files Modified

| File | Changes |
|------|---------|
| `frontend/public/audio-processor.js` | Added `peak` computation alongside RMS |
| `frontend/src/App.jsx` | Complete VAD rewrite: sliding-window, pre-speech buffer, audio gating, TTS playback with word-by-word reveal, barge-in support, debug panel |
| `app/main.py` | Server-side `_is_valid_transcript()` filter, TTS generation + base64 WebSocket delivery, debug logging |
| `app/services/voice_service.py` | ElevenLabs TTS (primary) + gTTS (fallback) — `text_to_speech_bytes_async()` |
