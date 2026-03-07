import { useEffect, useRef, useState, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const WS_BASE  = API_BASE.replace(/^http/i, 'ws');

// ── VAD tunables ────────────────────────────────────────────
// — Noise-floor calibration
const CALIBRATION_DURATION_MS = 2000;   // measure ambient noise for 2 s
const NOISE_FLOOR_MULTIPLIER  = 6;      // threshold = noise_floor × this
const MIN_ABSOLUTE_THRESHOLD  = 0.02;   // hard floor — rejects whispers & low ambient

// — Speech detection  (ratio-based: X of last Y frames must be above threshold)
const SPEECH_WINDOW_MS        = 400;    // sliding window length
const SPEECH_RATIO            = 0.5;    // at least 50 % of frames in window must be above
const VAD_SILENCE_TIMEOUT_MS  = 2000;   // 2 s of silence → end of speech
const VAD_SPEECH_MIN_MS       = 600;    // total speech must be at least this long
const MAX_CREST_FACTOR        = 10;     // peak/rms above this = impulsive noise

// — RMS smoothing  (exponential moving average to absorb spikes)
const RMS_SMOOTHING_ALPHA     = 0.35;   // 0 = heavy smoothing, 1 = raw

// — Pre-speech ring buffer (captures audio before speech is confirmed)
const PRE_SPEECH_CHUNKS       = 15;     // ~15 × 256 ms ≈ 3.8 s of look-back

// — TTS interrupt threshold multiplier (speech during TTS must be louder to avoid echo)
const TTS_INTERRUPT_MULTIPLIER = 2.5;  // threshold × this during TTS playback

// — Transcript filtering
const MIN_TRANSCRIPT_WORDS    = 2;      // ignore transcripts with fewer words
const MIN_TRANSCRIPT_CHARS    = 4;      // ignore transcripts shorter than this

// — STT hallucination phrases (Whisper outputs these on silence / noise)
const HALLUCINATION_PATTERNS = [
  /^thank(s| you)\s*(for)?\s*(watching|listening|viewing)/i,
  /^(please\s+)?(like|subscribe)/i,
  /^\s*you\s*$/i,
  /^(um+|uh+|hmm+|ah+|oh+)\s*\.?\s*$/i,
  /^\[.*\]$/,                            // [Music], [Applause], etc.
  /^\(.*\)$/,                            // (upbeat music), etc.
  /^\s*\.+\s*$/,                         // just dots / ellipsis
  /^bye[\s.!]*$/i,
];

// ── Helpers ─────────────────────────────────────────────────

/** Convert Float32 [-1,1] → Int16 PCM LE bytes */
function float32ToInt16Bytes(float32) {
  const buf = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

export default function App() {
  // ── State ───────────────────────────────────────────────
  const [conversationActive, setConversationActive] = useState(false);
  const [status, setStatus]       = useState('Tap "Start Conversation" to begin.');
  const [userText, setUserText]   = useState('');      // live / final transcript
  const [assistantText, setAssistantText] = useState('');
  const [messages, setMessages]   = useState([]);      // {role,content}[]
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [rmsLevel, setRmsLevel]   = useState(0);
  const [isCalibrating, setIsCalibrating] = useState(false);

  // ── Refs ────────────────────────────────────────────────
  const wsRef           = useRef(null);
  const audioCtxRef     = useRef(null);
  const workletNodeRef  = useRef(null);
  const streamRef       = useRef(null);
  const silenceTimerRef = useRef(null);
  const speechStartRef  = useRef(null);
  const hasSpeechRef    = useRef(false);
  const activeRef       = useRef(false);
  const chatEndRef      = useRef(null);
  const assistantBuf    = useRef('');

  // Noise-floor calibration refs
  const calibrationStartRef = useRef(null);  // Date.now() when calibration started
  const calibrationSamples  = useRef([]);    // RMS samples during calibration
  const noiseFloorRef       = useRef(0);     // computed noise floor
  const speechThresholdRef  = useRef(MIN_ABSOLUTE_THRESHOLD); // dynamic threshold
  const isCalibDoneRef      = useRef(false); // true once calibration is complete

  // Speech-confirmation gate: ratio of above-threshold frames in a sliding window
  const speechCandidateStartRef = useRef(null); // when first frame exceeded threshold
  const speechConfirmedRef      = useRef(false); // true once gate passed
  const vadFrameHistory         = useRef([]);    // recent {ts, above} entries

  // Smoothed RMS (exponential moving average)
  const smoothedRmsRef = useRef(0);

  // Pre-speech audio ring buffer — stores recent audio chunks so the start
  // of an utterance is not lost during the confirmation window.
  const preSpeechBufRef = useRef([]);

  // TTS playback state
  const [isTTSPlaying, setIsTTSPlaying] = useState(false);
  const ttsAudioRef    = useRef(null);   // HTMLAudioElement for TTS
  const ttsTextRef     = useRef('');      // full assistant text during TTS
  const wordTimerRef   = useRef(null);    // setInterval id for word reveal
  const ttsBlobUrlRef  = useRef(null);    // object URL to revoke on cleanup

  // Debug log buffer (shown in debug panel)
  const [debugLogs, setDebugLogs] = useState([]);
  const debugRef = useRef([]);
  const debugFlushTimer = useRef(null);
  const [showDebug, setShowDebug] = useState(false);

  // Pipeline latency metrics from backend
  const [latencyData, setLatencyData] = useState(null);
  const latencyHistoryRef = useRef([]);  // last N latency snapshots for averaging

  // Info modal
  const [showInfo, setShowInfo] = useState(false);

  /** Append a debug message (batched to reduce renders) */
  function dbg(msg) {
    const entry = `[${new Date().toLocaleTimeString('en-GB', { hour12: false })}] ${msg}`;
    console.log(`[VAD-DBG] ${msg}`);
    debugRef.current.push(entry);
    // Keep last 200 entries
    if (debugRef.current.length > 200) debugRef.current.shift();
    // Batch UI updates
    if (!debugFlushTimer.current) {
      debugFlushTimer.current = setTimeout(() => {
        setDebugLogs([...debugRef.current]);
        debugFlushTimer.current = null;
      }, 250);
    }
  }

  // Auto-scroll
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, userText, assistantText]);

  // Cleanup on unmount
  useEffect(() => () => teardown(), []);

  // ── Teardown everything ─────────────────────────────────
  function teardown() {
    activeRef.current = false;
    clearTimeout(silenceTimerRef.current);

    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;

    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;

    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;

    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    // Stop TTS if playing
    clearInterval(wordTimerRef.current);
    wordTimerRef.current = null;
    if (ttsAudioRef.current) {
      ttsAudioRef.current.pause();
      ttsAudioRef.current = null;
    }
    if (ttsBlobUrlRef.current) {
      URL.revokeObjectURL(ttsBlobUrlRef.current);
      ttsBlobUrlRef.current = null;
    }
    ttsTextRef.current = '';
    setIsTTSPlaying(false);

    // Reset calibration + speech-gate state
    calibrationStartRef.current     = null;
    calibrationSamples.current      = [];
    noiseFloorRef.current           = 0;
    speechThresholdRef.current      = MIN_ABSOLUTE_THRESHOLD;
    isCalibDoneRef.current          = false;
    speechCandidateStartRef.current = null;
    speechConfirmedRef.current      = false;
    vadFrameHistory.current         = [];
    smoothedRmsRef.current          = 0;
    preSpeechBufRef.current         = [];
    setIsCalibrating(false);
  }

  /** Stop TTS playback immediately and finalize partial text into chat */
  function stopTTS(reason) {
    dbg(`TTS interrupted: ${reason}`);
    clearInterval(wordTimerRef.current);
    wordTimerRef.current = null;

    if (ttsAudioRef.current) {
      ttsAudioRef.current.onended = null;  // prevent onended from firing
      ttsAudioRef.current.onerror = null;
      ttsAudioRef.current.pause();
      ttsAudioRef.current = null;
    }

    // Commit accumulated text so far to chat history
    const fullText = ttsTextRef.current;
    if (fullText.trim()) {
      setMessages(prev => [...prev, { role: 'assistant', content: fullText }]);
    }
    setAssistantText('');
    assistantBuf.current = '';
    ttsTextRef.current = '';
    setIsTTSPlaying(false);
    setIsProcessing(false);

    if (ttsBlobUrlRef.current) {
      URL.revokeObjectURL(ttsBlobUrlRef.current);
      ttsBlobUrlRef.current = null;
    }
  }

  // ── Start Conversation ──────────────────────────────────
  const startConversation = useCallback(async () => {
    teardown();

    setConversationActive(true);
    activeRef.current = true;
    setMessages([]);
    setUserText('');
    setAssistantText('');
    setStatus('Connecting…');
    assistantBuf.current = '';

    // 1. WebSocket
    const ws = new WebSocket(`${WS_BASE}/ws/voice`);
    wsRef.current = ws;

    ws.onopen = async () => {
      ws.send(JSON.stringify({ type: 'start_conversation' }));
      setStatus('Starting microphone…');

      try {
        // 2. Microphone
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 48000 },
        });
        streamRef.current = stream;

        // 3. AudioContext + Worklet
        const ctx = new AudioContext({ sampleRate: 48000 });
        audioCtxRef.current = ctx;

        await ctx.audioWorklet.addModule('/audio-processor.js');

        const source  = ctx.createMediaStreamSource(stream);
        const worklet = new AudioWorkletNode(ctx, 'audio-capture-processor');
        workletNodeRef.current = worklet;

        source.connect(worklet);
        worklet.connect(ctx.destination); // required to keep processing alive

        // 4. Handle messages from worklet
        worklet.port.onmessage = (e) => {
          if (!activeRef.current) return;

          if (e.data.type === 'audio') {
            if (!isCalibDoneRef.current) return;

            if (speechConfirmedRef.current) {
              // Speech confirmed — send audio normally
              const pcm = float32ToInt16Bytes(e.data.buffer);
              if (ws.readyState === WebSocket.OPEN) ws.send(pcm);
            } else {
              // Buffer recent chunks so start of utterance isn't lost
              preSpeechBufRef.current.push(e.data.buffer);
              if (preSpeechBufRef.current.length > PRE_SPEECH_CHUNKS) {
                preSpeechBufRef.current.shift();
              }
            }
          }

          if (e.data.type === 'vad') {
            const rawRms = e.data.rms;
            const peak   = e.data.peak;

            // EMA smoothing
            smoothedRmsRef.current =
              RMS_SMOOTHING_ALPHA * rawRms +
              (1 - RMS_SMOOTHING_ALPHA) * smoothedRmsRef.current;
            const rms = smoothedRmsRef.current;

            setRmsLevel(rms);

            // ── Phase 1: Noise-floor calibration ──────────
            if (!isCalibDoneRef.current) {
              if (!calibrationStartRef.current) {
                calibrationStartRef.current = Date.now();
                setIsCalibrating(true);
                setStatus('Calibrating noise floor… stay quiet.');
              }

              calibrationSamples.current.push(rawRms);

              if (Date.now() - calibrationStartRef.current >= CALIBRATION_DURATION_MS) {
                const samples = calibrationSamples.current;
                const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
                noiseFloorRef.current = avg;
                speechThresholdRef.current = Math.max(
                  avg * NOISE_FLOOR_MULTIPLIER,
                  MIN_ABSOLUTE_THRESHOLD,
                );
                isCalibDoneRef.current = true;
                setIsCalibrating(false);
                setStatus('Listening… speak naturally.');
                dbg(`Calibration done — floor=${avg.toFixed(5)}, threshold=${speechThresholdRef.current.toFixed(5)}`);
              }
              return;
            }

            // ── Phase 2: Speech detection (sliding-window ratio) ──
            // During TTS, raise the threshold to avoid echo triggering VAD
            const isTTSActive = ttsAudioRef.current && !ttsAudioRef.current.paused;
            const threshold = speechThresholdRef.current * (isTTSActive ? TTS_INTERRUPT_MULTIPLIER : 1);
            const crestFactor = rms > 0.001 ? peak / rms : 0;
            const isImpulsive = crestFactor > MAX_CREST_FACTOR;
            const frameAbove  = rms > threshold && !isImpulsive;

            // Record frame in sliding window
            const now = Date.now();
            vadFrameHistory.current.push({ ts: now, above: frameAbove });

            // Trim window to SPEECH_WINDOW_MS
            const cutoff = now - SPEECH_WINDOW_MS;
            while (vadFrameHistory.current.length > 0 && vadFrameHistory.current[0].ts < cutoff) {
              vadFrameHistory.current.shift();
            }

            // Compute ratio of above-threshold frames in window
            const totalFrames = vadFrameHistory.current.length;
            const aboveFrames = vadFrameHistory.current.filter(f => f.above).length;
            const ratio = totalFrames > 0 ? aboveFrames / totalFrames : 0;
            const speechDetected = ratio >= SPEECH_RATIO;

            if (speechDetected) {
              if (!speechCandidateStartRef.current) {
                speechCandidateStartRef.current = now;
              }

              if (!speechConfirmedRef.current) {
                // If TTS is playing, interrupt it first
                if (ttsAudioRef.current && !ttsAudioRef.current.paused) {
                  stopTTS('user started speaking');
                }

                // Confirm immediately once sliding window agrees
                speechConfirmedRef.current = true;
                hasSpeechRef.current = true;
                speechStartRef.current = now;
                setIsSpeaking(true);
                setStatus('Listening…');
                dbg(`Speech CONFIRMED — ratio=${ratio.toFixed(2)}, rms=${rms.toFixed(4)}, ` +
                    `threshold=${threshold.toFixed(4)}, prebuf=${preSpeechBufRef.current.length} chunks`);

                // Flush pre-speech buffer → backend gets the start of the utterance
                const flushed = preSpeechBufRef.current.length;
                for (const chunk of preSpeechBufRef.current) {
                  const pcm = float32ToInt16Bytes(chunk);
                  if (ws.readyState === WebSocket.OPEN) ws.send(pcm);
                }
                preSpeechBufRef.current = [];
                dbg(`Flushed ${flushed} pre-speech chunks (≈${(flushed * 256).toFixed(0)} ms)`);
              }

              // Cancel any pending silence timer
              clearTimeout(silenceTimerRef.current);
              silenceTimerRef.current = null;

            } else if (speechConfirmedRef.current && !silenceTimerRef.current) {
              // Speech was confirmed but now window says silence → start countdown
              dbg(`Silence detected — starting ${VAD_SILENCE_TIMEOUT_MS} ms countdown`);
              silenceTimerRef.current = setTimeout(() => {
                const dur = Date.now() - (speechStartRef.current || 0);
                if (dur >= VAD_SPEECH_MIN_MS && activeRef.current) {
                  dbg(`End-of-speech sent (duration=${dur} ms)`);
                  hasSpeechRef.current = false;
                  speechConfirmedRef.current = false;
                  speechCandidateStartRef.current = null;
                  vadFrameHistory.current = [];
                  preSpeechBufRef.current = [];
                  setIsSpeaking(false);
                  setIsProcessing(true);
                  setStatus('Processing your speech…');
                  if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'end_of_speech' }));
                  }
                } else {
                  dbg(`Discarded short speech (duration=${dur} ms < ${VAD_SPEECH_MIN_MS})`);
                  hasSpeechRef.current = false;
                  speechConfirmedRef.current = false;
                  speechCandidateStartRef.current = null;
                  vadFrameHistory.current = [];
                  preSpeechBufRef.current = [];
                  setIsSpeaking(false);
                  setStatus('Listening… speak naturally.');
                }
                silenceTimerRef.current = null;
              }, VAD_SILENCE_TIMEOUT_MS);
            }
          }
        };

        setStatus('Listening… speak naturally.');
      } catch (err) {
        console.error('Mic error:', err);
        setStatus('Microphone access denied.');
        teardown();
        setConversationActive(false);
      }
    };

    // ── WebSocket messages from server ────────────────────
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'conversation_started':
          setSessionId(data.session_id);
          dbg(`Session started: ${data.session_id}`);
          break;

        case 'partial_transcript':
          setUserText(data.text || '');
          dbg(`Partial transcript: "${data.text}"`);
          break;

        case 'final_transcript': {
          const text = (data.text || '').trim();
          const wordCount = text.split(/\s+/).filter(Boolean).length;
          dbg(`Final transcript: "${text}" (${wordCount} words, ${text.length} chars)`);

          // Reject short transcripts
          if (text.length < MIN_TRANSCRIPT_CHARS || wordCount < MIN_TRANSCRIPT_WORDS) {
            dbg(`REJECTED short transcript`);
            setUserText('');
            setIsProcessing(false);
            hasSpeechRef.current = false;
            speechConfirmedRef.current = false;
            speechCandidateStartRef.current = null;
            vadFrameHistory.current = [];
            preSpeechBufRef.current = [];
            setStatus('Listening… speak naturally.');
            break;
          }

          // Reject known STT hallucination patterns
          if (HALLUCINATION_PATTERNS.some(re => re.test(text))) {
            dbg(`REJECTED hallucination: "${text}"`);
            setUserText('');
            setIsProcessing(false);
            hasSpeechRef.current = false;
            speechConfirmedRef.current = false;
            speechCandidateStartRef.current = null;
            vadFrameHistory.current = [];
            preSpeechBufRef.current = [];
            setStatus('Listening… speak naturally.');
            break;
          }

          setUserText('');
          setMessages(prev => [...prev, { role: 'user', content: text }]);
          setAssistantText('');
          assistantBuf.current = '';
          break;
        }

        case 'assistant_stream':
          assistantBuf.current += (data.text || '');
          // Don't show streaming text — it will be revealed word-by-word during TTS
          break;

        case 'assistant_done': {
          const resp = (data.text || assistantBuf.current).trim();
          dbg(`Assistant done — length=${resp.length} chars`);
          if (!resp) {
            dbg(`WARNING: assistant response was empty`);
            assistantBuf.current = '';
            setAssistantText('');
            setIsProcessing(false);
            setStatus('Listening… speak naturally.');
          } else {
            // Save text; wait for tts_audio to start word-by-word reveal
            ttsTextRef.current = resp;
            setStatus('Generating voice…');
            dbg('Waiting for TTS audio…');
          }
          break;
        }

        case 'tts_audio': {
          const fullText = ttsTextRef.current;
          if (!fullText) {
            dbg('tts_audio received but no text stored — skipping');
            break;
          }

          dbg(`TTS audio received (${data.audio.length} b64 chars)`);

          // Decode base64 → Blob → Object URL
          const raw = atob(data.audio);
          const arr = new Uint8Array(raw.length);
          for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
          const blob = new Blob([arr], { type: 'audio/mpeg' });
          const url  = URL.createObjectURL(blob);
          ttsBlobUrlRef.current = url;

          const audio = new Audio(url);
          ttsAudioRef.current = audio;

          const words = fullText.split(/\s+/).filter(Boolean);
          let revealIdx = 0;

          setIsProcessing(false);
          setIsTTSPlaying(true);
          setAssistantText('');
          setStatus('Assistant is speaking…');

          audio.onloadedmetadata = () => {
            const dur = audio.duration; // seconds
            const interval = (dur * 1000) / words.length;
            dbg(`TTS duration=${dur.toFixed(2)}s, words=${words.length}, interval=${interval.toFixed(0)}ms`);

            wordTimerRef.current = setInterval(() => {
              revealIdx++;
              setAssistantText(words.slice(0, revealIdx).join(' '));
              if (revealIdx >= words.length) {
                clearInterval(wordTimerRef.current);
                wordTimerRef.current = null;
              }
            }, interval);
          };

          audio.onended = () => {
            dbg('TTS playback ended');
            clearInterval(wordTimerRef.current);
            wordTimerRef.current = null;

            // Finalize: add full message to chat, reset state
            setMessages(prev => [...prev, { role: 'assistant', content: fullText }]);
            setAssistantText('');
            assistantBuf.current = '';
            ttsTextRef.current = '';
            setIsTTSPlaying(false);
            setIsProcessing(false);
            hasSpeechRef.current = false;
            speechConfirmedRef.current = false;
            speechCandidateStartRef.current = null;
            vadFrameHistory.current = [];
            preSpeechBufRef.current = [];
            setStatus('Listening… speak naturally.');

            // Clean up blob URL
            URL.revokeObjectURL(url);
            ttsBlobUrlRef.current = null;
            ttsAudioRef.current = null;
          };

          audio.onerror = (err) => {
            dbg(`TTS audio playback error: ${err}`);
            // Fallback: show full text immediately
            setMessages(prev => [...prev, { role: 'assistant', content: fullText }]);
            setAssistantText('');
            assistantBuf.current = '';
            ttsTextRef.current = '';
            setIsTTSPlaying(false);
            setIsProcessing(false);
            setStatus('Listening… speak naturally.');
            URL.revokeObjectURL(url);
            ttsBlobUrlRef.current = null;
            ttsAudioRef.current = null;
          };

          audio.play().catch(err => {
            dbg(`TTS play() failed: ${err}`);
            // Autoplay blocked or error — show text immediately
            setMessages(prev => [...prev, { role: 'assistant', content: fullText }]);
            setAssistantText('');
            assistantBuf.current = '';
            ttsTextRef.current = '';
            setIsTTSPlaying(false);
            setIsProcessing(false);
            setStatus('Listening… speak naturally.');
          });
          break;
        }

        case 'tts_error': {
          dbg(`TTS error from server: ${data.message}`);
          // Fallback: show the full text without audio
          const fallbackText = ttsTextRef.current || assistantBuf.current;
          if (fallbackText.trim()) {
            setMessages(prev => [...prev, { role: 'assistant', content: fallbackText.trim() }]);
          }
          setAssistantText('');
          assistantBuf.current = '';
          ttsTextRef.current = '';
          setIsProcessing(false);
          hasSpeechRef.current = false;
          speechConfirmedRef.current = false;
          speechCandidateStartRef.current = null;
          vadFrameHistory.current = [];
          preSpeechBufRef.current = [];
          setStatus('Listening… speak naturally.');
          break;
        }

        case 'latency': {
          const l = data;
          setLatencyData(l);
          latencyHistoryRef.current.push(l);
          if (latencyHistoryRef.current.length > 20) latencyHistoryRef.current.shift();
          dbg(`⏱ LATENCY — STT: ${l.stt_ms}ms | LLM first-token: ${l.llm_first_token_ms}ms | LLM total: ${l.llm_total_ms}ms | TTS: ${l.tts_ms}ms | Pipeline: ${l.total_ms}ms | Audio: ${l.audio_duration_s}s`);
          break;
        }

        case 'error':
          dbg(`SERVER ERROR: ${data.message}`);
          setIsProcessing(false);
          hasSpeechRef.current = false;
          speechConfirmedRef.current = false;
          speechCandidateStartRef.current = null;
          vadFrameHistory.current = [];
          preSpeechBufRef.current = [];
          setStatus(`Error: ${data.message}`);
          setTimeout(() => {
            if (activeRef.current) setStatus('Listening… speak naturally.');
          }, 3000);
          break;

        default:
          break;
      }
    };

    ws.onclose = () => {
      if (activeRef.current) {
        setStatus('Connection lost. Reconnecting…');
        setTimeout(() => activeRef.current && startConversation(), 2000);
      }
    };

    ws.onerror = () => setStatus('WebSocket error.');
  }, []);

  // ── Stop Conversation ───────────────────────────────────
  const stopConversation = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop_conversation' }));
    }
    teardown();
    setConversationActive(false);
    setIsSpeaking(false);
    setIsProcessing(false);
    setUserText('');
    setAssistantText('');
    setStatus('Conversation ended.');
  }, []);

  // ── Render ──────────────────────────────────────────────
  return (
    <main className="mx-auto flex h-dvh w-full max-w-3xl flex-col bg-linear-to-b from-slate-50 to-slate-100 text-slate-900">

      {/* ── Header ─────────────────────────────────────── */}
      <header className="flex items-center justify-between border-b border-slate-200 bg-white/80 px-5 py-4 backdrop-blur">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            🦷 SmileCare AI
          </h1>
          <p className="mt-0.5 text-xs text-slate-500">{status}</p>
        </div>

        {conversationActive ? (
          <button
            onClick={stopConversation}
            className="rounded-full bg-red-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-red-200 transition hover:bg-red-700 active:scale-95"
          >
            Stop Conversation
          </button>
        ) : (
          <button
            onClick={startConversation}
            className="rounded-full bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-200 transition hover:bg-emerald-700 active:scale-95"
          >
            Start Conversation
          </button>
        )}
      </header>

      {/* ── Chat area ──────────────────────────────────── */}
      <section className="flex-1 overflow-y-auto px-4 py-4 space-y-3">

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-slate-800 border border-slate-200'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {/* Live user transcript (partial / streaming) */}
        {userText && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl bg-blue-400/80 px-4 py-2.5 text-sm text-white italic shadow-sm">
              {userText}
              <span className="ml-1 inline-block animate-pulse">▎</span>
            </div>
          </div>
        )}

        {/* Live assistant response (TTS word-by-word or streaming) */}
        {assistantText && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-slate-800 shadow-sm">
              {isTTSPlaying && (
                <span className="mr-1.5 inline-block align-middle animate-pulse">🔊</span>
              )}
              {assistantText}
              <span className="ml-1 inline-block animate-pulse">▎</span>
            </div>
          </div>
        )}

        {/* Processing indicator */}
        {isProcessing && !assistantText && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl bg-white border border-slate-200 px-4 py-2.5 text-sm text-slate-500 shadow-sm">
              <span className="flex gap-1">
                <span className="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
              Thinking…
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </section>

      {/* ── Footer / voice indicator ───────────────────── */}
      {conversationActive && (
        <footer className="flex flex-col items-center gap-2 border-t border-slate-200 bg-white/80 px-5 py-4 backdrop-blur">

          {/* Audio level ring */}
          <div className="relative flex items-center justify-center">
            <div
              className={`h-16 w-16 rounded-full transition-all duration-150 ${
                isCalibrating
                  ? 'bg-amber-400 shadow-lg shadow-amber-200 animate-pulse'
                  : isTTSPlaying
                    ? 'bg-violet-500 shadow-lg shadow-violet-300 animate-pulse'
                    : isSpeaking
                      ? 'bg-emerald-500 shadow-lg shadow-emerald-300'
                      : 'bg-slate-300'
              }`}
              style={{
                transform: `scale(${isTTSPlaying ? 1.15 : 1 + Math.min(rmsLevel * 15, 0.6)})`,
              }}
            />
            <div className="absolute inset-0 flex items-center justify-center">
              {isTTSPlaying ? (
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" className="h-7 w-7">
                  <path d="M11.383 3.076A1 1 0 0 1 12 4v16a1 1 0 0 1-1.707.707L5.586 16H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h1.586l4.707-4.707a1 1 0 0 1 1.09-.217Z" />
                  <path d="M16 7.5a6.5 6.5 0 0 1 0 9" strokeWidth="2" stroke="white" fill="none" />
                  <path d="M19 5a10 10 0 0 1 0 14" strokeWidth="2" stroke="white" fill="none" />
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" className="h-7 w-7">
                  <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z" />
                  <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V21h-2a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-3.07A7 7 0 0 0 19 11Z" />
                </svg>
              )}
            </div>
          </div>

          <p className="text-xs text-slate-500">
            {isCalibrating ? 'Calibrating…' : isTTSPlaying ? 'Speaking…' : isSpeaking ? 'Listening…' : isProcessing ? 'Processing…' : 'Waiting for speech'}
          </p>
        </footer>
      )}

      {/* ── Debug panel (collapsible) ──────────────────── */}
      <div className="fixed bottom-0 right-0 z-50 w-96 max-w-full">
        <button
          onClick={() => setShowDebug(d => !d)}
          className="ml-auto block rounded-tl-lg bg-slate-800 px-3 py-1 text-xs font-mono text-slate-300 hover:bg-slate-700"
        >
          {showDebug ? '▼ Hide Debug' : '▲ Show Debug'}
        </button>
        {showDebug && (
          <div className="bg-slate-900 border-t border-slate-700">
            {/* ── Latency dashboard ─────────────────────── */}
            {latencyData && (
              <div className="p-2 border-b border-slate-700">
                <p className="text-[10px] font-mono text-cyan-400 font-bold mb-1">⏱ Pipeline Latency (last turn)</p>
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] font-mono">
                  <span className="text-slate-400">STT (Deepgram Nova-3):</span>
                  <span className={latencyData.stt_ms < 800 ? 'text-emerald-400' : latencyData.stt_ms < 1500 ? 'text-yellow-400' : 'text-red-400'}>
                    {latencyData.stt_ms} ms
                  </span>
                  <span className="text-slate-400">LLM first token:</span>
                  <span className={latencyData.llm_first_token_ms < 500 ? 'text-emerald-400' : latencyData.llm_first_token_ms < 1000 ? 'text-yellow-400' : 'text-red-400'}>
                    {latencyData.llm_first_token_ms} ms
                  </span>
                  <span className="text-slate-400">LLM total:</span>
                  <span className={latencyData.llm_total_ms < 2000 ? 'text-emerald-400' : latencyData.llm_total_ms < 4000 ? 'text-yellow-400' : 'text-red-400'}>
                    {latencyData.llm_total_ms} ms
                  </span>
                  <span className="text-slate-400">TTS (Deepgram Aura):</span>
                  <span className={latencyData.tts_ms < 800 ? 'text-emerald-400' : latencyData.tts_ms < 1500 ? 'text-yellow-400' : 'text-red-400'}>
                    {latencyData.tts_ms} ms
                  </span>
                  <span className="text-slate-400 font-bold">Total pipeline:</span>
                  <span className={`font-bold ${latencyData.total_ms < 2000 ? 'text-emerald-400' : latencyData.total_ms < 4000 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {latencyData.total_ms} ms
                  </span>
                  <span className="text-slate-400">Audio captured:</span>
                  <span className="text-slate-300">{latencyData.audio_duration_s}s</span>
                </div>
                {latencyHistoryRef.current.length > 1 && (
                  <p className="text-[9px] text-slate-500 mt-1">
                    Avg over {latencyHistoryRef.current.length} turns: {Math.round(latencyHistoryRef.current.reduce((s, d) => s + d.total_ms, 0) / latencyHistoryRef.current.length)} ms
                  </p>
                )}
              </div>
            )}
            {/* ── Log entries ───────────────────────────── */}
            <div className="h-48 overflow-y-auto p-2 text-[10px] leading-relaxed font-mono text-green-400">
              {debugLogs.length === 0 && (
                <p className="text-slate-500">No debug events yet. Start a conversation.</p>
              )}
              {debugLogs.map((line, i) => (
                <div key={i} className={
                  line.includes('ERROR') || line.includes('REJECTED') || line.includes('WARNING')
                    ? 'text-red-400'
                    : line.includes('CONFIRMED') || line.includes('done')
                      ? 'text-emerald-400'
                      : line.includes('LATENCY')
                        ? 'text-cyan-400'
                        : ''
                }>
                  {line}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Floating Info Button ────────────────────────── */}
      <button
        onClick={() => setShowInfo(true)}
        className="fixed bottom-16 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg shadow-blue-200 transition hover:bg-blue-700 hover:scale-105 active:scale-95"
        title="Clinic Information"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4" />
          <path d="M12 8h.01" />
        </svg>
      </button>

      {/* ── Info Modal ─────────────────────────────────── */}
      {showInfo && (
        <div className="fixed inset-0 z-100 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={() => setShowInfo(false)}>
          <div
            className="relative w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl bg-white shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4 rounded-t-2xl">
              <h2 className="text-lg font-bold text-slate-900">🦷 SmileCare Dental Clinic</h2>
              <button
                onClick={() => setShowInfo(false)}
                className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
                  <path d="M18 6 6 18" />
                  <path d="m6 6 12 12" />
                </svg>
              </button>
            </div>

            {/* Modal body */}
            <div className="px-6 py-5 space-y-5">

              {/* Clinic Info */}
              <section>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-100 text-blue-600 text-xs">🏥</span>
                  Clinic Information
                </h3>
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600 space-y-1.5">
                  <p><span className="font-medium text-slate-700">Name:</span> SmileCare Dental Clinic</p>
                  <p><span className="font-medium text-slate-700">Address:</span> 123 Dental Avenue, Suite 200, Mysore, KA 570001</p>
                  <p><span className="font-medium text-slate-700">Hours:</span> Mon–Fri 9:00 AM – 5:00 PM, Sat 9:00 AM – 3:00 PM</p>
                  <p><span className="font-medium text-slate-700">Phone:</span> +1-555-0100</p>
                  <p><span className="font-medium text-slate-700">Email:</span> hello@smilecare.com</p>
                  <p><span className="font-medium text-slate-700">Emergency:</span> +1-555-0199 (24/7)</p>
                </div>
              </section>

              {/* Hospital Services */}
              <section>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 text-xs">🩺</span>
                  Hospital Services
                </h3>
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      'General Checkup', 'Teeth Cleaning', 'Dental X-Ray', 'Tooth Filling',
                      'Root Canal', 'Tooth Extraction', 'Teeth Whitening', 'Dental Crown',
                      'Dental Bridge', 'Braces & Orthodontics', 'Dental Implant', 'Gum Treatment',
                      'Porcelain Veneer', 'Wisdom Tooth Removal', 'Emergency Services',
                    ].map(s => (
                      <div key={s} className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 flex shrink-0" />
                        <span>{s}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* Departments / Dentists */}
              <section>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-100 text-violet-600 text-xs">👨‍⚕️</span>
                  Departments & Dentists
                </h3>
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600 space-y-2">
                  <div className="flex justify-between"><span className="font-medium">Dr. Sarah Johnson</span><span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">General Dentistry</span></div>
                  <div className="flex justify-between"><span className="font-medium">Dr. Michael Chen</span><span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full">Orthodontics</span></div>
                  <div className="flex justify-between"><span className="font-medium">Dr. Emily Rodriguez</span><span className="text-xs bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full">Endodontics</span></div>
                </div>
              </section>

              {/* AI Assistant Capabilities */}
              <section>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-100 text-amber-600 text-xs">🤖</span>
                  AI Assistant Capabilities
                </h3>
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
                  <div className="grid grid-cols-1 gap-2">
                    {[
                      ['📅', 'Book, cancel, or reschedule appointments by voice'],
                      ['🔍', 'Check available time slots for any date'],
                      ['💰', 'Get service details, durations, and pricing'],
                      ['👨‍⚕️', 'Find dentists by specialization'],
                      ['📋', 'Look up your appointment history'],
                      ['ℹ️', 'Answer clinic FAQs (hours, location, contact)'],
                      ['🦷', 'Provide general dental health advice'],
                    ].map(([icon, text]) => (
                      <div key={text} className="flex items-start gap-2">
                        <span className="flex shrink-0">{icon}</span>
                        <span>{text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* Tech Stack */}
              <section>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-200 text-slate-600 text-xs">⚡</span>
                  Technology Stack
                </h3>
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
                  <div className="grid grid-cols-2 gap-2">
                    <div><span className="font-medium">STT:</span> Deepgram Nova-3</div>
                    <div><span className="font-medium">LLM:</span> Groq Llama 3</div>
                    <div><span className="font-medium">TTS:</span> Deepgram Aura</div>
                    <div><span className="font-medium">Backend:</span> FastAPI</div>
                    <div><span className="font-medium">Frontend:</span> React + Vite</div>
                    <div><span className="font-medium">Transport:</span> WebSocket</div>
                  </div>
                </div>
              </section>

            </div>

            {/* Modal footer */}
            <div className="sticky bottom-0 border-t border-slate-200 bg-slate-50 px-6 py-3 text-center rounded-b-2xl">
              <p className="text-xs text-slate-400">Say "Start Conversation" to talk with SmileCare AI</p>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
