import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { playAudio } from './lib/audio'
import { ErrorBanner } from './components/ErrorBanner'
import { Transcript } from './components/Transcript'
import { Composer } from './components/Composer'
import { StartScreen } from './components/StartScreen'
import { CodingWorkspace } from './components/CodingWorkspace'
import { Evaluation } from './components/Evaluation'
import { useVoices } from './hooks/useVoices'
import { useApiReady } from './hooks/useApiReady'
import { useEvaluation } from './hooks/useEvaluation'
import { useResumeUpload } from './hooks/useResumeUpload'
import { useRecorder } from './hooks/useRecorder'
import './App.css'
import mark from './assets/mark.svg'

// The watching interviewer (ADR 0018): snapshot on a typing pause; poll for
// check-ins. The backend owns the real policy (offer, interval, cooldowns,
// cap) - the frontend just asks often and usually hears "silent".
const SNAPSHOT_DEBOUNCE_MS = 2000
const CHECK_IN_POLL_MS = 25000

// Inferred labels are already human-readable; only the curated bank's own slug
// needs prettifying (ADR 0023).
const DOMAIN_LABELS = { ml_genai: 'ML / GenAI' }

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
  const [stage, setStage] = useState(null) // intro | warm_up | done
  const [warmUpSource, setWarmUpSource] = useState(null) // resume | bank
  const [dsa, setDsa] = useState(null) // DsaPayload for the current coding question
  const [code, setCode] = useState('')
  const [runReport, setRunReport] = useState(null)
  const [dsaSubmitted, setDsaSubmitted] = useState(false)
  const [running, setRunning] = useState(false)
  const chatEndRef = useRef(null)
  const statusRef = useRef(status)
  statusRef.current = status

  const { voices, voice, setVoice } = useVoices(setError)
  const apiReady = useApiReady()
  const { evaluation, evaluating, resetEvaluation } = useEvaluation({ phase, sessionId, onError: setError })
  const { resumeId, resumeName, resumeStatus, handleResumeChange } = useResumeUpload({ onError: setError })
  const { startRecording, stopRecording } = useRecorder({
    sessionId,
    setStatus,
    onError: setError,
    onTranscript: sendTranscript,
  })

  // Keep the newest message in view, chat-app style (wireframe v1).
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, status])

  // Snapshot on a typing pause (ADR 0018). Fire-and-forget: a lost snapshot
  // just means the watcher sees slightly older code. Skip the untouched
  // starter code: this effect also re-fires when a new question's starter
  // code loads into `code`, and posting that would falsely mark the watcher's
  // typing clock as started, permanently foreclosing the Offer for a
  // Candidate who never actually typed.
  useEffect(() => {
    if (!dsa || dsaSubmitted || !sessionId || code === dsa.starter_code) return
    const timer = setTimeout(() => {
      fetch(api(`/api/session/${sessionId}/dsa/snapshot`), {
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
        const resp = await fetch(api(`/api/session/${sessionId}/dsa/check-in`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voice }),
        })
        if (!resp.ok) return
        const data = await resp.json()
        if (data.action === 'silent') return
        setHistory((h) => [...h, { role: 'assistant', content: data.remark }])
        if (statusRef.current === 'idle') {
          await playAudio(data.audio_b64, setStatus)
        }
      } catch {
        // a failed check-in is a silent one
      }
    }, CHECK_IN_POLL_MS)
    return () => clearInterval(timer)
  }, [dsa, dsaSubmitted, sessionId, voice])

  async function startInterview(allowBankFallback = false) {
    setError(null)
    setStatus('thinking')
    try {
      const resp = await fetch(api('/api/session'), {
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
      await playAudio(data.audio_b64, setStatus)
    } catch {
      // A raw fetch error is not something to show a Candidate. On a first
      // visit the likeliest cause is simply that the API is still waking
      // (ADR 0025), so say that rather than printing the exception.
      setError(
        apiReady
          ? 'Could not start the interview. Please try again.'
          : 'The interviewer is still waking up. Give it a few seconds and try again.'
      )
      setStatus('idle')
    }
  }

  function startNewInterview() {
    setScreen('start')
    setSessionId(null)
    setHistory([])
    setPhase(null)
    setQuestionNumber(null)
    setTotalQuestions(null)
    setError(null)
    setStatus('idle')
    setStage(null)
    setWarmUpSource(null)
    setDsa(null)
    setCode('')
    setRunReport(null)
    setDsaSubmitted(false)
    setFallbackOffer(null)
    setSessionDomain(null)
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
      const resp = await fetch(api(`/api/session/${sessionId}/answer`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: text, voice }),
      })
      if (!resp.ok) throw new Error(`backend returned ${resp.status}`)
      const data = await resp.json()
      setLatencyMs(Math.round(performance.now() - t0))
      setHistory([...newHistory, { role: 'assistant', content: data.reply }])
      applyProgress(data)
      await playAudio(data.audio_b64, setStatus)
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
      const resp = await fetch(api(`/api/session/${sessionId}/dsa/run`), {
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
      const resp = await fetch(api(`/api/session/${sessionId}/dsa/submit`), {
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
      await playAudio(data.audio_b64, setStatus)
    } catch (err) {
      setError(String(err))
      setStatus('idle')
    }
  }

  function handleTextSubmit(e) {
    e.preventDefault()
    sendTranscript(draft)
    setDraft('')
  }

  if (screen === 'start') {
    return (
      <StartScreen
        apiReady={apiReady}
        status={status}
        error={error}
        onDismissError={() => setError(null)}
        resumeName={resumeName}
        resumeStatus={resumeStatus}
        onResumeChange={handleResumeChange}
        resumeId={resumeId}
        fallbackOffer={fallbackOffer}
        onStartInterview={startInterview}
        onCancelFallback={() => setFallbackOffer(null)}
      />
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
        <div className="brand">
          <span className="brand-name">Callback</span>
          <img className="brand-mark" src={mark} alt="" aria-hidden="true" />
          {progressLabel && <span className="progress">{progressLabel}</span>}
        </div>
        <div className="controls">
          <label className="voice-row">
            Voice:
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              {Object.entries(voices).map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
          </label>
          <span
            className={`status status-${status}`}
            title={latencyMs !== null ? `last turn: ${latencyMs} ms` : undefined}
          >
            {status}
          </span>
        </div>
      </header>

      <ErrorBanner error={error} onDismiss={() => setError(null)} />

      {resumeId && warmUpSource === 'bank' && (
        <p className="hint">
          Resume grounding unavailable — this warm-up uses curated questions.
        </p>
      )}
      {sessionDomain && (
        <p className="hint">Interview field: {DOMAIN_LABELS[sessionDomain] ?? sessionDomain}</p>
      )}

      <section className="chat">
        <Transcript history={history} done={done} endRef={chatEndRef} status={status} />

        {done ? (
          <div className="composer">
            <button
              type="button"
              onClick={() => {
                startNewInterview()
                resetEvaluation()
              }}
            >
              Start new interview
            </button>
          </div>
        ) : (
          <>
            {dsa && !dsaSubmitted && (
              <CodingWorkspace
                dsa={dsa}
                code={code}
                onCodeChange={setCode}
                running={running}
                status={status}
                onRun={runCode}
                onSubmit={submitCode}
                runReport={runReport}
              />
            )}
            <Composer
              value={draft}
              onDraftChange={setDraft}
              onSubmit={handleTextSubmit}
              status={status}
              placeholder={dsa && !dsaSubmitted ? 'Think aloud or ask the interviewer' : 'Type here'}
              onStartRecording={startRecording}
              onStopRecording={stopRecording}
            />
          </>
        )}
      </section>

      {done && evaluating && <p className="hint">Scoring your interview…</p>}

      {done && evaluation && <Evaluation evaluation={evaluation} />}

    </main>
  )
}

export default App
