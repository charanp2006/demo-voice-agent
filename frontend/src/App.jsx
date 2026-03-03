import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Mic, Send, Square } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState('Tap mic to Start');
  const [isRecording, setIsRecording] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [textInput, setTextInput] = useState('');

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const chatRef = useRef(null);
  const audioRef = useRef(null);
  const audioObjectUrlRef = useRef(null);

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

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = handleStopRecording;
      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
      setStatus('Recording... tap mic again to send');
    } catch (_error) {
      setStatus('Mic access denied');
    }
  }

  function stopRecording() {
    if (!mediaRecorderRef.current) {
      return;
    }
    setIsLoading(true);
    setStatus('Processing...');
    mediaRecorderRef.current.stop();
  }

  async function handleStopRecording() {
    const recorder = mediaRecorderRef.current;
    const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
    const file = new File([blob], 'voice.webm', { type: 'audio/webm' });
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_BASE}/voice`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        throw new Error('Voice request failed');
      }

      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: data.transcription || '' },
        { role: 'assistant', content: data.response || '' },
      ]);

      await playAudioFromBase64(data.audio_base64, data.audio_mime_type);
    } catch (_error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Failed to process voice request.' },
      ]);
    } finally {
      recorder?.stream?.getTracks()?.forEach((track) => track.stop());
      mediaRecorderRef.current = null;
      chunksRef.current = [];
      setIsRecording(false);
      setIsLoading(false);
      setStatus('Tap mic to record');
    }
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

  return (
    <main className="mx-auto flex h-dvh w-full max-w-4xl flex-col bg-slate-50 p-4 text-slate-900">
      <header className="mb-3 border-b border-slate-200 pb-3">
        <h1 className="text-lg font-semibold">Clinic Voice Assistant</h1>
        <p className="mt-1 text-sm text-slate-500">{status}</p>
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
        <div className="flex items-center gap-2">
          <textarea
            value={textInput}
            onChange={(event) => setTextInput(event.target.value)}
            onKeyDown={handleInputKeyDown}
            rows={1}
            placeholder="Type your message..."
            className="max-h-28 flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
            disabled={isLoading}
          />

          <button
            type="button"
            onClick={sendTextMessage}
            disabled={isLoading || isRecording || !textInput.trim()}
            className="rounded-lg bg-blue-600 p-2 text-white disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Send message"
          >
            <Send className="h-5 w-5" />
          </button>

          <button
            type="button"
            onClick={toggleMic}
            disabled={isLoading}
            className={`rounded-lg p-2 text-white disabled:cursor-not-allowed disabled:opacity-50 ${
              isRecording ? 'bg-red-600' : 'bg-emerald-600'
            }`}
            aria-label={isRecording ? 'Stop recording' : 'Start recording'}
          >
            {isRecording ? <Square className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
          </button>
        </div>
        <audio ref={audioRef} className="mt-2 w-full" controls />
      </section>
    </main>
  );
}
