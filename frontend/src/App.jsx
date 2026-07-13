import { useEffect, useRef, useState } from 'react'
import './App.css'

function App() {
  const [history, setHistory] = useState([])
  const [status, setStatus] = useState('idle') // idle | recording | transcribing | thinking | speaking
  const [draft, setDraft] = useState('')
  const [latencyMs, setLatencyMs] = useState(null)
  const [error, setError] = useState(null)
  const [voices, setVoices] = useState({})
  const [voice, setVoice] = useState('')
  const recorderRef = useRef(null)

  useEffect(() => {
    fetch('/api/voices')
      .then((r) => r.json())
      .then((data) => {
        setVoices(data.voices)
        setVoice(data.default)
      })
      .catch(() => setError('backend not reachable — is it running on port 8000?'))
  }, [])

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
        body: JSON.stringify({ history: newHistory, voice }),
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

  async function startRecording() {
    setError(null)
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('Microphone permission denied — allow it in the address bar, or type below.')
      return
    }
    const recorder = new MediaRecorder(stream)
    const chunks = []
    recorder.ondataavailable = (e) => chunks.push(e.data)
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      setStatus('transcribing')
      try {
        const blob = new Blob(chunks, { type: recorder.mimeType })
        const form = new FormData()
        form.append('file', blob, 'answer.webm')
        const resp = await fetch('/api/transcribe', { method: 'POST', body: form })
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}))
          throw new Error(body.detail || `transcription failed (${resp.status})`)
        }
        const data = await resp.json()
        await sendTranscript(data.transcript)
      } catch (err) {
        setError(String(err))
        setStatus('idle')
      }
    }
    recorderRef.current = recorder
    recorder.start()
    setStatus('recording')
  }

  function stopRecording() {
    recorderRef.current?.stop()
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
        {status === 'recording' ? (
          <button className="recording" onClick={stopRecording}>⏹ Stop &amp; send</button>
        ) : (
          <button onClick={startRecording} disabled={status !== 'idle'}>
            🎤 Answer by voice
          </button>
        )}
        <span className={`status status-${status}`}>{status}</span>
        {latencyMs !== null && <span className="latency">last turn: {latencyMs} ms</span>}
      </div>

      <label className="voice-row">
        Interviewer voice:
        <select value={voice} onChange={(e) => setVoice(e.target.value)}>
          {Object.entries(voices).map(([id, label]) => (
            <option key={id} value={id}>{label}</option>
          ))}
        </select>
      </label>

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
