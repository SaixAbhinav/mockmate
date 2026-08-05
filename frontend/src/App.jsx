import { useEffect, useRef, useState } from 'react'
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
import { useSession } from './hooks/useSession'
import { useDsaRound } from './hooks/useDsaRound'
import './App.css'
import mark from './assets/mark.svg'

// Inferred labels are already human-readable; only the curated bank's own slug
// needs prettifying (ADR 0023).
const DOMAIN_LABELS = { ml_genai: 'ML / GenAI' }

function App() {
  const [status, setStatus] = useState('idle') // idle | recording | transcribing | thinking | speaking
  const [draft, setDraft] = useState('')
  const [error, setError] = useState(null)
  const chatEndRef = useRef(null)
  const statusRef = useRef(status)
  statusRef.current = status

  const { voices, voice, setVoice } = useVoices(setError)
  const apiReady = useApiReady()
  const { resumeId, resumeName, resumeStatus, handleResumeChange } = useResumeUpload({ onError: setError })

  // The two hooks are mutually dependent: the Session decides when a new
  // Question starts, the coding round owns the editor that has to react to it.
  // A ref breaks the cycle without moving editor state back up here.
  const roundRef = useRef(null)
  const session = useSession({
    voice,
    resumeId,
    apiReady,
    setStatus,
    onError: setError,
    onNewQuestion: (payload) => roundRef.current.startQuestion(payload),
    onResetRound: () => roundRef.current.resetDsaRound(),
  })
  const round = useDsaRound({
    sessionId: session.sessionId,
    voice,
    dsa: session.dsa,
    statusRef,
    setStatus,
    onError: setError,
    appendAssistant: session.appendAssistant,
    applySubmitProgress: session.applySubmitProgress,
  })
  roundRef.current = round

  const { screen, sessionId, history, phase, stage, questionNumber, totalQuestions } = session
  const { sessionDomain, warmUpSource, fallbackOffer, latencyMs, dsa } = session
  const { code, runReport, dsaSubmitted, running } = round

  const { evaluation, evaluating, resetEvaluation } = useEvaluation({ phase, sessionId, onError: setError })
  const { startRecording, stopRecording } = useRecorder({
    sessionId,
    setStatus,
    onError: setError,
    onTranscript: session.sendTranscript,
  })

  // Keep the newest message in view, chat-app style (wireframe v1).
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, status])

  function handleTextSubmit(e) {
    e.preventDefault()
    session.sendTranscript(draft)
    setDraft('')
  }

  function handleNewInterview() {
    session.startNewInterview()
    resetEvaluation()
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
        onStartInterview={session.startInterview}
        onCancelFallback={() => session.setFallbackOffer(null)}
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
        <p className="hint">
          Interview field: {DOMAIN_LABELS[sessionDomain] ?? sessionDomain}
        </p>
      )}

      <section className="chat">
        <Transcript history={history} done={done} endRef={chatEndRef} status={status} />

        {done ? (
          <div className="composer">
            <button type="button" onClick={handleNewInterview}>
              Start new interview
            </button>
          </div>
        ) : (
          <>
            {dsa && !dsaSubmitted && (
              <CodingWorkspace
                dsa={dsa}
                code={code}
                onCodeChange={round.setCode}
                running={running}
                status={status}
                onRun={round.runCode}
                onSubmit={round.submitCode}
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
