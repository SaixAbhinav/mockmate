import { useEffect, useRef, useState } from 'react'
import './App.css'

// Domain picker (ML/GenAI only for v1, ADR 0008).
const DOMAINS = { ml_genai: 'ML / GenAI' }

function App() {
  const [screen, setScreen] = useState('domain') // domain | interview
  const [domain, setDomain] = useState('ml_genai')
  const [sessionId, setSessionId] = useState(null)
  const [history, setHistory] = useState([])
  const [phase, setPhase] = useState(null) // null | advancing | probing | clarifying | done
  const [questionNumber, setQuestionNumber] = useState(null)
  const [totalQuestions, setTotalQuestions] = useState(null)
  const [status, setStatus] = useState('idle') // idle | recording | transcribing | thinking | speaking
  const [draft, setDraft] = useState('')
  const [latencyMs, setLatencyMs] = useState(null)
  const [error, setError] = useState(null)
  const [voices, setVoices] = useState({})
  const [voice, setVoice] = useState('')
  const [evaluation, setEvaluation] = useState(null)
  const [evaluating, setEvaluating] = useState(false)
  const [stage, setStage] = useState(null) // intro | warm_up | done
  const [warmUpSource, setWarmUpSource] = useState(null) // resume | bank
  const [resumeId, setResumeId] = useState(null)
  const [resumeName, setResumeName] = useState('')
  const [resumeStatus, setResumeStatus] = useState('none') // none | uploading | ready | failed
  const recorderRef = useRef(null)
  const chatEndRef = useRef(null)
  const resumeUploadTokenRef = useRef(0)

  useEffect(() => {
    fetch('/api/voices')
      .then((r) => r.json())
      .then((data) => {
        setVoices(data.voices)
        setVoice(data.default)
      })
      .catch(() => setError('backend not reachable — is it running on port 8000?'))
  }, [])

  // Keep the newest message in view, chat-app style (wireframe v1).
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, status])

  // The Evaluation only exists once the Session is done.
  useEffect(() => {
    if (phase !== 'done' || !sessionId) return
    const controller = new AbortController()
    setEvaluating(true)
    fetch(`/api/session/${sessionId}/evaluation`, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`evaluation failed (${r.status})`)
        return r.json()
      })
      .then(setEvaluation)
      .catch((err) => {
        if (err.name !== 'AbortError') setError(String(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setEvaluating(false)
      })
    return () => controller.abort()
  }, [phase, sessionId])

  async function playAudio(audioB64) {
    setStatus('speaking')
    const audio = new Audio(`data:audio/mp3;base64,${audioB64}`)
    audio.onended = () => setStatus('idle')
    await audio.play()
  }

  async function startInterview() {
    setError(null)
    setStatus('thinking')
    try {
      const resp = await fetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain, voice, resume_id: resumeId }),
      })
      if (!resp.ok) throw new Error(`backend returned ${resp.status}`)
      const data = await resp.json()
      setSessionId(data.session_id)
      setHistory([{ role: 'assistant', content: data.first_question }])
      setQuestionNumber(data.question_number)
      setTotalQuestions(data.total_questions)
      setStage(data.stage)
      setWarmUpSource(data.warm_up_source)
      setPhase(null)
      setScreen('interview')
      await playAudio(data.audio_b64)
    } catch (err) {
      setError(String(err))
      setStatus('idle')
    }
  }

  function startNewInterview() {
    setScreen('domain')
    setSessionId(null)
    setHistory([])
    setPhase(null)
    setQuestionNumber(null)
    setTotalQuestions(null)
    setError(null)
    setStatus('idle')
    setEvaluation(null)
    setEvaluating(false)
    setStage(null)
    setWarmUpSource(null)
  }

  async function handleResumeChange(e) {
    const file = e.target.files[0]
    if (!file) return
    const token = ++resumeUploadTokenRef.current
    setResumeStatus('uploading')
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const resp = await fetch('/api/resume', { method: 'POST', body: form })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail || `resume upload failed (${resp.status})`)
      }
      const data = await resp.json()
      if (token !== resumeUploadTokenRef.current) return // a newer upload superseded this one
      setResumeId(data.resume_id)
      setResumeName(file.name)
      setResumeStatus('ready')
    } catch (err) {
      if (token !== resumeUploadTokenRef.current) return // a newer upload superseded this one
      setResumeId(null)
      setResumeStatus('failed')
      setError(String(err))
    }
  }

  async function sendTranscript(transcript) {
    const text = transcript.trim()
    if (!text || !sessionId) return
    const newHistory = [...history, { role: 'user', content: text }]
    setHistory(newHistory)
    setStatus('thinking')
    setError(null)
    const t0 = performance.now()
    try {
      const resp = await fetch(`/api/session/${sessionId}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: text, voice }),
      })
      if (!resp.ok) throw new Error(`backend returned ${resp.status}`)
      const data = await resp.json()
      setLatencyMs(Math.round(performance.now() - t0))
      setHistory([...newHistory, { role: 'assistant', content: data.reply }])
      setPhase(data.phase)
      setQuestionNumber(data.question_number)
      setTotalQuestions(data.total_questions)
      setStage(data.stage)
      await playAudio(data.audio_b64)
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

  if (screen === 'domain') {
    return (
      <main className="wrap">
        <header className="topbar">
          <h1>MockMate</h1>
        </header>
        <section className="domain-picker">
          <label className="voice-row">
            Domain:
            <select value={domain} onChange={(e) => setDomain(e.target.value)}>
              {Object.entries(DOMAINS).map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
          </label>
          <label className="voice-row">
            Resume (optional):
            <input type="file" accept=".pdf,.txt" onChange={handleResumeChange} />
          </label>
          {resumeStatus === 'uploading' && <p className="hint">Uploading resume…</p>}
          {resumeStatus === 'ready' && (
            <p className="hint">Warm-up questions will be grounded in {resumeName}</p>
          )}
          <button
            onClick={startInterview}
            disabled={status === 'thinking' || resumeStatus === 'uploading'}
          >
            {status === 'thinking'
              ? (resumeId ? 'Reading your resume…' : 'Starting…')
              : 'Start interview'}
          </button>
        </section>
        {error && <p className="error">{error}</p>}
      </main>
    )
  }

  const done = phase === 'done'
  const STAGE_LABELS = { intro: 'intro', warm_up: 'warm-up' }
  const progressLabel = questionNumber && totalQuestions
    ? `${STAGE_LABELS[stage] ? STAGE_LABELS[stage] + ' · ' : ''}` +
      `question ${questionNumber} of ${totalQuestions}` +
      (phase === 'probing' ? ' · probing' : phase === 'clarifying' ? ' · clarifying' : '')
    : null

  return (
    <main className="wrap">
      <header className="topbar">
        <h1>MockMate</h1>
        <div className="controls">
          <label className="voice-row">
            Voice:
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              {Object.entries(voices).map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
          </label>
          <span className={`status status-${status}`}>{status}</span>
          {progressLabel && <span className="progress">{progressLabel}</span>}
          {latencyMs !== null && <span className="latency">last turn: {latencyMs} ms</span>}
        </div>
      </header>

      {resumeId && warmUpSource === 'bank' && (
        <p className="hint">
          Resume grounding unavailable — this warm-up uses curated questions.
        </p>
      )}

      <section className="chat">
        <div className="messages">
          {history.map((m, i) => (
            <p
              key={i}
              className={done && i === history.length - 1 ? 'wrap-up' : m.role}
            >
              <strong>{m.role === 'user' ? 'You' : 'Interviewer'}:</strong> {m.content}
            </p>
          ))}
          {(status === 'thinking' || status === 'transcribing') && (
            <p className="hint">{status}…</p>
          )}
          <div ref={chatEndRef} />
        </div>

        {done ? (
          <div className="composer">
            <button type="button" onClick={startNewInterview}>
              Start new interview
            </button>
          </div>
        ) : (
          <form onSubmit={handleTextSubmit} className="composer">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Type here"
              disabled={status === 'thinking'}
            />
            <button type="submit" disabled={status === 'thinking' || !draft.trim()}>
              Send
            </button>
            {status === 'recording' ? (
              <button type="button" className="recording" onClick={stopRecording}>
                ⏹ Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={startRecording}
                disabled={status !== 'idle'}
                aria-label="Answer by voice"
              >
                🎤
              </button>
            )}
          </form>
        )}
      </section>

      {done && evaluating && <p className="hint">Scoring your interview…</p>}

      {done && evaluation && (
        <section className="evaluation">
          <h2>How you did</h2>
          <p className="evaluation-assessment">{evaluation.assessment}</p>

          <div className="chips">
            <span className="score-chip coverage">
              answered <strong>{evaluation.coverage.answered}</strong> of{' '}
              {evaluation.coverage.total}
            </span>
            {Object.entries(evaluation.averages).map(([dimension, value]) => (
              <span key={dimension} className="score-chip">
                {dimension}: <strong>{value ?? '—'}</strong>/5
              </span>
            ))}
          </div>

          {evaluation.strengths.length > 0 && (
            <>
              <h3>Strengths</h3>
              <ul>{evaluation.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </>
          )}

          {evaluation.improvements.length > 0 && (
            <>
              <h3>Work on</h3>
              <ul>{evaluation.improvements.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </>
          )}

          <h3>Question by question</h3>
          {evaluation.questions.map((q, i) => (
            <div key={i} className="evaluation-question">
              <p className="evaluation-question-text">{q.question}</p>
              {q.skipped ? (
                <p className="hint">Not answered</p>
              ) : q.unscored ? (
                <p className="hint">Couldn't be scored</p>
              ) : (
                <>
                  <div className="chips">
                    <span className="score-chip">correctness: <strong>{q.correctness}</strong>/5</span>
                    <span className="score-chip">depth: <strong>{q.depth}</strong>/5</span>
                    <span className="score-chip">clarity: <strong>{q.clarity}</strong>/5</span>
                  </div>
                  <p>{q.comment}</p>
                </>
              )}
            </div>
          ))}
        </section>
      )}

      {error && <p className="error">{error}</p>}
    </main>
  )
}

export default App
