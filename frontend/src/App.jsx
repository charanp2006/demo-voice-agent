import { useEffect, useRef, useState, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const WS_BASE  = API_BASE.replace(/^http/i, 'ws');

// ── VAD tunables ────────────────────────────────────────────
const VAD_SILENCE_THRESHOLD  = 0.008;   // RMS below this = silence
const VAD_SILENCE_TIMEOUT_MS = 2500;    // 2.5 s of silence → end of speech
const VAD_SPEECH_MIN_MS      = 500;     // ignore silence bursts shorter than this

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
            // Convert & send binary PCM chunk
            const pcm = float32ToInt16Bytes(e.data.buffer);
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(pcm);
            }
          }

          if (e.data.type === 'vad') {
            const rms = e.data.rms;
            setRmsLevel(rms);

            if (rms > VAD_SILENCE_THRESHOLD) {
              // Speech detected
              if (!hasSpeechRef.current) {
                hasSpeechRef.current = true;
                speechStartRef.current = Date.now();
                setIsSpeaking(true);
                setStatus('Listening…');
              }
              // Reset silence timer
              clearTimeout(silenceTimerRef.current);
              silenceTimerRef.current = null;
            } else if (hasSpeechRef.current && !silenceTimerRef.current) {
              // Start silence countdown
              silenceTimerRef.current = setTimeout(() => {
                const speechDuration = Date.now() - (speechStartRef.current || 0);
                if (speechDuration >= VAD_SPEECH_MIN_MS && activeRef.current) {
                  // Silence confirmed → end of speech
                  hasSpeechRef.current = false;
                  setIsSpeaking(false);
                  setIsProcessing(true);
                  setStatus('Processing your speech…');

                  if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'end_of_speech' }));
                  }
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
          break;

        case 'partial_transcript':
          setUserText(data.text || '');
          break;

        case 'final_transcript':
          setUserText('');
          setMessages(prev => [...prev, { role: 'user', content: data.text }]);
          setAssistantText('');
          assistantBuf.current = '';
          break;

        case 'assistant_stream':
          assistantBuf.current += (data.text || '');
          setAssistantText(assistantBuf.current);
          break;

        case 'assistant_done':
          setMessages(prev => [...prev, { role: 'assistant', content: assistantBuf.current }]);
          setAssistantText('');
          assistantBuf.current = '';
          setIsProcessing(false);
          hasSpeechRef.current = false;
          setStatus('Listening… speak naturally.');
          break;

        case 'error':
          setIsProcessing(false);
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

        {/* Live assistant response (streaming) */}
        {assistantText && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-slate-800 shadow-sm">
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
                isSpeaking
                  ? 'bg-emerald-500 shadow-lg shadow-emerald-300'
                  : 'bg-slate-300'
              }`}
              style={{
                transform: `scale(${1 + Math.min(rmsLevel * 15, 0.6)})`,
              }}
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" className="h-7 w-7">
                <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z" />
                <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V21h-2a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-3.07A7 7 0 0 0 19 11Z" />
              </svg>
            </div>
          </div>

          <p className="text-xs text-slate-500">
            {isSpeaking ? 'Listening…' : isProcessing ? 'Processing…' : 'Waiting for speech'}
          </p>
        </footer>
      )}
    </main>
  );
}
