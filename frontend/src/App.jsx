import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Mic, Send, Square } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const WS_BASE = API_BASE.replace(/^http/i, 'ws');

export default function App() {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState('Conversation ended. Click "Start Conversation" to begin.');
  const [isRecording, setIsRecording] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [textInput, setTextInput] = useState('');
  const [isWsConnected, setIsWsConnected] = useState(false);
  const [conversationActive, setConversationActive] = useState(false);
  const [socketState, setSocketState] = useState('disconnected');
  const [chunkSentCount, setChunkSentCount] = useState(0);
  const [chunkAckCount, setChunkAckCount] = useState(0);
  const [lastWsEvent, setLastWsEvent] = useState('-');
  const [wsTimeline, setWsTimeline] = useState([]);

  const mediaRecorderRef = useRef(null);
  const chatRef = useRef(null);
  const audioRef = useRef(null);
  const audioObjectUrlRef = useRef(null);
  const wsRef = useRef(null);
  const conversationActiveRef = useRef(false);

  useEffect(() => {
    loadHistory();
  }, []);

  useEffect(() => {
    return () => {
      if (audioObjectUrlRef.current) {
        URL.revokeObjectURL(audioObjectUrlRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  async function loadHistory() {
    try {
      const res = await fetch(`${API_BASE}/history`);
      if (!res.ok) {
        return;
      }
      const data = await res.json();
      const historyMessages = data.messages || [];
      setMessages(historyMessages);
    } catch (_error) {
      // Ignore history load errors
    }
  }

  async function playAudioFromBase64(audioBase64, mimeType = 'audio/mpeg') {
    if (!audioRef.current || !audioBase64) {
      return;
    }

    const binary = atob(audioBase64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }

    const blob = new Blob([bytes], { type: mimeType });
    const objectUrl = URL.createObjectURL(blob);

    if (audioObjectUrlRef.current) {
      URL.revokeObjectURL(audioObjectUrlRef.current);
    }

    audioObjectUrlRef.current = objectUrl;
    audioRef.current.src = objectUrl;
    await audioRef.current.play().catch(() => null);
  }

  async function sendTextMessage() {
    const trimmed = textInput.trim();
    if (!trimmed || isLoading || isRecording) {
      return;
    }

    setIsLoading(true);
    setStatus('Validating and generating response...');
    setTextInput('');

    try {
      setMessages((prev) => [...prev, { role: 'user', content: trimmed }]);

      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed }),
      });

      if (!res.ok) {
        throw new Error('Chat request failed');
      }

      const data = await res.json();
      const responseText = data.response || '';

      setMessages((prev) => [...prev, { role: 'assistant', content: responseText }]);
      await playAudioFromBase64(data.audio_base64, data.audio_mime_type);
    } catch (_error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Failed to process text request.' },
      ]);
    } finally {
      setIsLoading(false);
      setStatus('Tap mic to record');
    }
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64String = reader.result.split(',')[1];
        resolve(base64String);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function startRecording() {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setStatus('Voice socket disconnected. Retry in a moment.');
      trackWsEvent('send_blocked', 'socket_not_open');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      const recordedChunks = [];
      setChunkSentCount(0);
      setChunkAckCount(0);
      trackWsEvent('recording_started');

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          recordedChunks.push(event.data);
          setChunkSentCount((prev) => prev + 1);
        }
      };

      mediaRecorderRef.current = mediaRecorder;
      mediaRecorderRef.current.recordedChunks = recordedChunks;
      mediaRecorder.start(1500);
      setIsRecording(true);
      setStatus('Recording... tap mic again to send');
    } catch (_error) {
      setStatus('Mic access denied');
    }
  }

  async function stopRecording() {
    if (!mediaRecorderRef.current) {
      return;
    }

    const recorder = mediaRecorderRef.current;
    const recordedChunks = recorder.recordedChunks || [];
    
    recorder.stop();
    recorder.stream?.getTracks()?.forEach((track) => track.stop());
    setIsRecording(false);
    setIsLoading(true);
    setStatus('Processing voice...');
    trackWsEvent('recording_stopped');

    // Wait a bit for ondataavailable to fire
    setTimeout(async () => {
      if (!recordedChunks.length) {
        setIsLoading(false);
        setStatus('No audio recorded');
        mediaRecorderRef.current = null;
        return;
      }

      try {
        // Combine all chunks into single blob
        const audioBlob = new Blob(recordedChunks, { type: 'audio/webm' });
        const base64Audio = await blobToBase64(audioBlob);

        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(
            JSON.stringify({
              type: 'audio_data',
              data: base64Audio,
            }),
          );
          trackWsEvent('audio_sent');
        } else {
          setIsLoading(false);
          setStatus('Voice socket disconnected. Retry in a moment.');
          trackWsEvent('audio_send_failed', 'socket_not_open');
        }
      } catch (error) {
        setIsLoading(false);
        setStatus('Failed to process audio');
        trackWsEvent('audio_process_failed', error.message);
      } finally {
        mediaRecorderRef.current = null;
      }
    }, 100);
  }

  function toggleMic() {
    if (isLoading) {
      return;
    }
    if (isRecording) {
      stopRecording();
      return;
    }
    startRecording();
  }

  function handleInputKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendTextMessage();
    }
  }

  function trackWsEvent(type, details = '') {
    const label = details ? `${type}: ${details}` : type;
    setLastWsEvent(label);
    setWsTimeline((prev) => {
      const next = [...prev, { id: `${Date.now()}-${Math.random()}`, label }];
      return next.slice(-6);
    });
  }

  function connectWebSocket(isAutoReconnect = false) {
    // Don't auto-reconnect if conversation is not active
    if (isAutoReconnect && !conversationActiveRef.current) {
      setSocketState('disconnected');
      return;
    }

    setSocketState('connecting');
    const ws = new WebSocket(`${WS_BASE}/ws/voice`);

    ws.onopen = () => {
      setIsWsConnected(true);
      setSocketState('open');
      if (conversationActiveRef.current) {
        setStatus('Tap mic to record');
      }
      trackWsEvent('socket_open');
    };

    ws.onclose = () => {
      setIsWsConnected(false);
      setSocketState('closed');
      mediaRecorderRef.current?.stream?.getTracks()?.forEach((track) => track.stop());
      mediaRecorderRef.current = null;
      setIsRecording(false);
      setIsLoading(false);
      trackWsEvent('socket_close');

      // Only auto-reconnect if conversation is still active
      if (conversationActiveRef.current) {
        setStatus('Connection lost - reconnecting...');
        setTimeout(() => {
          trackWsEvent('reconnecting');
          connectWebSocket(true);
        }, 2000);
      } else {
        setStatus('Conversation ended. Click "Start Conversation" to begin.');
      }
    };

    ws.onerror = () => {
      setSocketState('error');
      setStatus('Voice socket error');
      trackWsEvent('socket_error');
    };

    ws.onmessage = async (event) => {
      const data = JSON.parse(event.data);
      trackWsEvent(data.type || 'unknown');

      if (data.type === 'ack') {
        setChunkAckCount((prev) => prev + 1);
      }

      if (data.type === 'transcription') {
        setMessages((prev) => [...prev, { role: 'user', content: data.text || '' }]);
        setStatus('Generating response...');
      }

      if (data.type === 'agent_text') {
        setMessages((prev) => [...prev, { role: 'assistant', content: data.text || '' }]);
      }

      if (data.type === 'error') {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: data.message || 'Voice request failed.' },
        ]);
        setIsLoading(false);
        setStatus('Tap mic to record');
      }

      if (data.type === 'audio_ready' && data.audio_url) {
        const audioUrl = `${API_BASE}${data.audio_url}`;
        if (audioRef.current) {
          if (audioObjectUrlRef.current) {
            URL.revokeObjectURL(audioObjectUrlRef.current);
            audioObjectUrlRef.current = null;
          }
          audioRef.current.src = audioUrl;
          await audioRef.current.play().catch(() => null);
        }
        setIsLoading(false);
        setStatus('Tap mic to record');
      }
    };

    wsRef.current = ws;
  }

  function startConversation() {
    setConversationActive(true);
    conversationActiveRef.current = true;
    setMessages([]);
    setStatus('Loading...');
    trackWsEvent('conversation_started');
    connectWebSocket();
  }

  function stopConversation() {
    setConversationActive(false);
    conversationActiveRef.current = false;
    mediaRecorderRef.current?.stream?.getTracks()?.forEach((track) => track.stop());
    mediaRecorderRef.current = null;
    setIsRecording(false);
    setIsLoading(false);
    setChunkSentCount(0);
    setChunkAckCount(0);
    setStatus('Conversation ended. Click "Start Conversation" to begin.');
    trackWsEvent('conversation_stopped');

    // Close WebSocket gracefully
    if (wsRef.current) {
      wsRef.current.onclose = null; // Prevent auto-reconnect
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsWsConnected(false);
    setSocketState('disconnected');
  }

  useEffect(() => {
    // Load history on mount
    loadHistory();

    // Cleanup on unmount
    return () => {
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, []);

  return (
    <main className="mx-auto flex h-dvh w-full max-w-4xl flex-col bg-slate-50 p-4 text-slate-900">
      <header className="mb-3 border-b border-slate-200 pb-3">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Clinic Voice Assistant</h1>
            <p className="mt-1 text-sm text-slate-500">{status}</p>
          </div>
          {conversationActive ? (
            <button
              type="button"
              onClick={stopConversation}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Stop conversation"
            >
              Stop Conversation
            </button>
          ) : (
            <button
              type="button"
              onClick={startConversation}
              className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Start conversation"
            >
              Start Conversation
            </button>
          )}
        </div>
      </header>

      <section
        ref={chatRef}
        className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-slate-200 bg-white p-3"
      >
        {messages.map((message, index) => {
          const isUser = message.role === 'user';
          return (
            <div key={`${message.role}-${index}`} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm leading-relaxed ${
                  isUser ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-900'
                }`}
              >
                {message.content}
              </div>
            </div>
          );
        })}

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <LoaderCircle className="h-4 w-4 animate-spin" />
            Processing...
          </div>
        )}
      </section>

      <section className="mt-3 rounded-xl border border-slate-200 bg-white p-2">
        <div className="mb-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs text-slate-600">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>Socket: {socketState}</span>
            <span>Chunks sent: {chunkSentCount}</span>
            <span>Chunks acked: {chunkAckCount}</span>
            <span>Last event: {lastWsEvent}</span>
          </div>
          {wsTimeline.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {wsTimeline.map((item) => (
                <span key={item.id} className="rounded bg-white px-2 py-0.5 text-[11px] text-slate-500">
                  {item.label}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <textarea
            value={textInput}
            onChange={(event) => setTextInput(event.target.value)}
            onKeyDown={handleInputKeyDown}
            rows={1}
            placeholder={conversationActive ? "Type your message..." : "Start a conversation first..."}
            className="max-h-28 flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
            disabled={isLoading || !conversationActive}
          />

          <button
            type="button"
            onClick={sendTextMessage}
            disabled={isLoading || isRecording || !textInput.trim() || !conversationActive}
            className="rounded-lg bg-blue-600 p-2 text-white disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Send message"
          >
            <Send className="h-5 w-5" />
          </button>

          <button
            type="button"
            onClick={toggleMic}
            disabled={isLoading || !isWsConnected || !conversationActive}
            className={`rounded-lg p-2 text-white disabled:cursor-not-allowed disabled:opacity-50 ${
              isRecording ? 'bg-red-600' : 'bg-emerald-600'
            }`}
            aria-label={isRecording ? 'Stop recording' : 'Start recording'}
            title={!conversationActive ? 'Start a conversation first' : ''}
          >
            {isRecording ? <Square className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
          </button>
        </div>
        <audio ref={audioRef} className="mt-2 w-full" controls />
      </section>
    </main>
  );
}
