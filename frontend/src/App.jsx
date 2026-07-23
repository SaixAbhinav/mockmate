import { useEffect, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import './App.css'

// The watching interviewer (ADR 0018): snapshot on a typing pause; poll for
// check-ins. The backend owns the real policy (offer, interval, cooldowns,
// cap) - the frontend just asks often and usually hears "silent".
const SNAPSHOT_DEBOUNCE_MS = 2000
const CHECK_IN_POLL_MS = 25000

function App() {
  const [screen, setScreen] = useState('start') // start | interview
  const [sessionDomain, setSessionDomain] = useState(null) // derived label (ADR 0023)
  const [fallbackOffer, setFallbackOffer] = useState(null) // 409 detail, or null
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
  const [dsa, setDsa] = useState(null) // DsaPayload for the current coding question
  const [code, setCode] = useState('')
  const [runReport, setRunReport] = useState(null)
  const [dsaSubmitted, setDsaSubmitted] = useState(false)
  const [running, setRunning] = useState(false)
  const recorderRef = useRef(null)
  const chatEndRef = useRef(null)
  const resumeUploadTokenRef = useRef(0)
  const statusRef = useRef(status)
  statusRef.current = status

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

  // Snapshot on a typing pause (ADR 0018). Fire-and-forget: a lost snapshot
  // just means the watcher sees slightly older code. Skip the untouched
  // starter code: this effect also re-fires when a new question's starter
  // code loads into `code`, and posting that would falsely mark the watcher's
  // typing clock as started, permanently foreclosing the Offer for a
  // Candidate who never actually typed.
  useEffect(() => {
    if (!dsa || dsaSubmitted || !sessionId || code === dsa.starter_code) return
    const timer = setTimeout(() => {
      fetch(`/api/session/${sessionId}/dsa/snapshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      }).catch(() => {})
    }, SNAPSHOT_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [code, dsa, dsaSubmitted, sessionId])

  // Check-in poll (ADR 0018): the interviewer may stay silent, offer to
  // clarify, ask about the code, or give a hint. Errors are silent - nobody
  // asked for this request. If the Candidate is no longer idle when the reply
  // arrives, show the text but never talk over them (the transcript is the
  // truth; audio is best-effort).
  useEffect(() => {
    if (!dsa || dsaSubmitted || !sessionId) return
    const timer = setInterval(async () => {
      if (statusRef.current !== 'idle') return
      try {
        const resp = await fetch(`/api/session/${sessionId}/dsa/check-in`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voice }),
        })
        if (!resp.ok) return
        const data = await resp.json()
        if (data.action === 'silent') return
        setHistory((h) => [...h, { role: 'assistant', content: data.remark }])
        if (statusRef.current === 'idle') {
          await playAudio(data.audio_b64)
        }
      } catch {
        // a failed check-in is a silent one
      }
    }, CHECK_IN_POLL_MS)
    return () => clearInterval(timer)
  }, [dsa, dsaSubmitted, sessionId, voice])

  async function playAudio(audioB64) {
    setStatus('speaking')
    const audio = new Audio(`data:audio/mp3;base64,${audioB64}`)
    audio.onended = () => setStatus('idle')
    await audio.play()
  }

  async function startInterview(allowBankFallback = false) {
    setError(null)
    setStatus('thinking')
    try {
      const resp = await fetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voice,
          resume_id: resumeId,
          allow_bank_fallback: allowBankFallback,
        }),
      })
      // 409 is not an error: the backend is asking whether a general interview
      // is acceptable, because it could not tailor one (ADR 0023).
      if (resp.status === 409) {
        const body = await resp.json()
        setFallbackOffer(body.detail)
        setStatus('idle')
        return
      }
      if (!resp.ok) throw new Error(`backend returned ${resp.status}`)
      const data = await resp.json()
      setFallbackOffer(null)
      setSessionId(data.session_id)
      setSessionDomain(data.domain)
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

  // Deliberately does NOT reset resumeId/resumeName/resumeStatus: the uploaded
  // resume stays valid for a second interview without re-uploading.
  function startNewInterview() {
    setScreen('start')
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
    setDsa(null)
    setCode('')
    setRunReport(null)
    setDsaSubmitted(false)
    setFallbackOffer(null)
    setSessionDomain(null)
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

  // Every advancing response can move the interview onto (or off) a coding
  // question; the editor state follows the dsa payload - but only resets when
  // the payload belongs to a *different* question (ADR 0019: a coding-chat
  // reply carries the same question's payload).
  function applyProgress(data) {
    setPhase(data.phase)
    setStage(data.stage)
    const payload = data.dsa ?? null
    setDsa(payload)
    if (payload && data.question_number !== questionNumber) {
      setCode(payload.starter_code)
      setRunReport(null)
      setDsaSubmitted(false)
    }
    setQuestionNumber(data.question_number)
    setTotalQuestions(data.total_questions)
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
      applyProgress(data)
      await playAudio(data.audio_b64)
    } catch (err) {
      setHistory(history) // roll back the optimistic append so a failed turn leaves no orphan message
      setError(String(err))
      setStatus('idle')
    }
  }

  async function runCode() {
    setRunning(true)
    setError(null)
    try {
      const resp = await fetch(`/api/session/${sessionId}/dsa/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
      if (!resp.ok) throw new Error(`run failed (${resp.status})`)
      setRunReport(await resp.json())
    } catch (err) {
      setError(String(err))
    } finally {
      setRunning(false)
    }
  }

  async function submitCode() {
    setStatus('thinking')
    setError(null)
    try {
      const resp = await fetch(`/api/session/${sessionId}/dsa/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, voice }),
      })
      if (!resp.ok) throw new Error(`submit failed (${resp.status})`)
      const data = await resp.json()
      setRunReport(data.run)
      setDsaSubmitted(true)
      setHistory((h) => [...h, { role: 'assistant', content: data.reply }])
      setPhase(data.phase)
      setQuestionNumber(data.question_number)
      setTotalQuestions(data.total_questions)
      setStage(data.stage)
      await playAudio(data.audio_b64)
    } catch (err) {
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

  if (screen === 'start') {
    return (
      <main className="wrap">
        <header className="topbar">
          <h1>MockMate</h1>
        </header>
        <section className="start-panel">
          <label className="voice-row">
            Resume:
            <input type="file" accept=".pdf,.txt" onChange={handleResumeChange} />
          </label>
          {resumeStatus === 'uploading' && <p className="hint">Uploading resume…</p>}
          {resumeStatus === 'ready' && (
            <p className="hint">Your interview will be built around {resumeName}</p>
          )}
          {!resumeId && resumeStatus !== 'uploading' && (
            <p className="hint">
              No resume — this will be a general ML/GenAI interview.
            </p>
          )}

          {fallbackOffer ? (
            <div className="fallback-offer">
              <p>{fallbackOffer.message}</p>
              <button onClick={() => startInterview(true)} disabled={status === 'thinking'}>
                Start the general interview
              </button>
              <button
                className="secondary"
                onClick={() => setFallbackOffer(null)}
                disabled={status === 'thinking'}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => startInterview(false)}
              disabled={status === 'thinking' || resumeStatus === 'uploading'}
            >
              {status === 'thinking'
                ? (resumeId ? 'Reading your resume…' : 'Starting…')
                : 'Start interview'}
            </button>
          )}
        </section>
        {error && <p className="error">{error}</p>}
      </main>
    )
  }

  const done = phase === 'done'
  const STAGE_LABELS = { intro: 'intro', warm_up: 'warm-up', dsa: 'coding' }
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
      {sessionDomain && (
        <p className="hint">Interview field: {sessionDomain}</p>
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
          <>
            {dsa && !dsaSubmitted && (
              <div className="dsa-pane">
                <p className="dsa-signature"><code>{dsa.signature}</code></p>
                <CodeMirror
                  value={code}
                  height="220px"
                  extensions={[python()]}
                  onChange={setCode}
                />
                <div className="dsa-actions">
                  <button type="button" onClick={runCode} disabled={running || status === 'thinking'}>
                    {running ? 'Running…' : '▶ Run tests'}
                  </button>
                  <button
                    type="button"
                    onClick={submitCode}
                    disabled={running || status === 'thinking'}
                  >
                    {status === 'thinking' ? 'Submitting…' : 'Submit'}
                  </button>
                </div>
                {runReport && (
                  <div className="dsa-results">
                    {runReport.status === 'ok' ? (
                      <p>
                        <strong>{runReport.passed}</strong> of {runReport.total} test cases passed
                      </p>
                    ) : (
                      <p className="error">{runReport.error}</p>
                    )}
                    {runReport.results.filter((r) => !r.passed).map((r, i) => (
                      <p key={i} className="dsa-fail">
                        args: <code>{JSON.stringify(r.args)}</code> · expected{' '}
                        <code>{JSON.stringify(r.expected)}</code> · got <code>{r.got}</code>
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
            <form onSubmit={handleTextSubmit} className="composer">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={
                  dsa && !dsaSubmitted ? 'Think aloud or ask the interviewer' : 'Type here'
                }
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
          </>
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

          {evaluation.dsa && evaluation.dsa.questions.length > 0 && (
            <>
              <h3>Coding round</h3>
              <div className="chips">
                {Object.entries(evaluation.dsa.averages).map(([dimension, value]) => (
                  <span key={dimension} className="score-chip">
                    {dimension.replace('_', ' ')}: <strong>{value ?? '—'}</strong>/5
                  </span>
                ))}
                <span className="score-chip coverage">
                  hints used <strong>{evaluation.dsa.hints_used}</strong>
                </span>
              </div>
              {evaluation.dsa.questions.map((q, i) => (
                <div key={i} className="evaluation-question">
                  <p className="evaluation-question-text">{q.question}</p>
                  {q.skipped ? (
                    <p className="hint">Never submitted</p>
                  ) : (
                    <div className="chips">
                      <span className="score-chip coverage">
                        tests: <strong>{q.tests.passed}</strong>/{q.tests.total}
                        {q.tests.status !== 'ok' && ` (${q.tests.status})`}
                      </span>
                      {!q.unscored && (
                        <>
                          <span className="score-chip">
                            code quality: <strong>{q.code_quality}</strong>/5
                          </span>
                          <span className="score-chip">
                            approach: <strong>{q.approach}</strong>/5
                          </span>
                        </>
                      )}
                    </div>
                  )}
                  {q.unscored && <p className="hint">The code itself couldn't be scored</p>}
                  {q.comment && <p>{q.comment}</p>}
                  {(q.hints > 0 || q.runs > 0) && (
                    <p className="hint">
                      {q.hints} hint(s) · {q.runs} test run(s) while coding
                    </p>
                  )}
                </div>
              ))}
            </>
          )}
        </section>
      )}

      {error && <p className="error">{error}</p>}
    </main>
  )
}

export default App
