import { useRef, useState } from 'react'
import './App.css'

// Browser STT (ADR 0004): free, zero infra. Chrome/Edge expose it as webkit-prefixed.
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition

function App() {
  const [history, setHistory] = useState([])
  const [status, setStatus] = useState('idle') // idle | listening | thinking | speaking
  const [draft, setDraft] = useState('')
  const [latencyMs, setLatencyMs] = useState(null)
  const [error, setError] = useState(null)
  const recognitionRef = useRef(null)

  async function sendTranscript(transcript) {
    const text = transcript.trim()
    if (!text) return
    const newHistory = [...history, { role: 'user', content: text }]
    setHistory(newHistory)
    setStatus('thinking')
    setError(null)
    const t0 = performance.now()
    try {
      const resp = await fetch('/api/turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: newHistory }),
      })
      if (!resp.ok) throw new Error(`backend returned ${resp.status}`)
      const data = await resp.json()
      setLatencyMs(Math.round(performance.now() - t0))
      setHistory([...newHistory, { role: 'assistant', content: data.reply }])
      setStatus('speaking')
      const audio = new Audio(`data:audio/mp3;base64,${data.audio_b64}`)
      audio.onended = () => setStatus('idle')
      await audio.play()
    } catch (err) {
      setHistory(history) // roll back the optimistic append so a failed turn leaves no orphan message
      setError(String(err))
      setStatus('idle')
    }
  }

  function startListening() {
    if (!SpeechRecognition) {
      setError('This browser has no speech recognition — use the text box below.')
      return
    }
    const rec = new SpeechRecognition()
    recognitionRef.current = rec
    rec.lang = 'en-IN'
    rec.interimResults = false
    rec.onresult = (e) => sendTranscript(e.results[0][0].transcript)
    rec.onerror = (e) => {
      setError(`speech recognition error: ${e.error}`)
      setStatus('idle')
    }
    rec.onend = () => setStatus((s) => (s === 'listening' ? 'idle' : s))
    setStatus('listening')
    rec.start()
  }

  function handleTextSubmit(e) {
    e.preventDefault()
    sendTranscript(draft)
    setDraft('')
  }

  return (
    <main className="wrap">
      <h1>MockMate</h1>
      <p className="tagline">Walking skeleton — one spoken interview turn, end to end.</p>

      <div className="controls">
        <button onClick={startListening} disabled={status !== 'idle'}>
          {status === 'listening' ? 'Listening…' : '🎤 Answer by voice'}
        </button>
        <span className={`status status-${status}`}>{status}</span>
        {latencyMs !== null && <span className="latency">last turn: {latencyMs} ms</span>}
      </div>

      <form onSubmit={handleTextSubmit} className="fallback">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="No mic? Type your answer here"
          disabled={status === 'thinking'}
        />
        <button type="submit" disabled={status === 'thinking' || !draft.trim()}>
          Send
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      <section className="transcript">
        {history.length === 0 && (
          <p className="hint">
            Press the mic (or type) to start — the interviewer replies out loud.
          </p>
        )}
        {history.map((m, i) => (
          <p key={i} className={m.role}>
            <strong>{m.role === 'user' ? 'You' : 'Interviewer'}:</strong> {m.content}
          </p>
        ))}
      </section>
    </main>
  )
}

export default App
