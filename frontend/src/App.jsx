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
import './App.css'
import mark from './assets/mark.svg'

// The watching interviewer (ADR 0018): snapshot on a typing pause; poll for
// check-ins. The backend owns the real policy (offer, interval, cooldowns,
// cap) - the frontend just asks often and usually hears "silent".
const SNAPSHOT_DEBOUNCE_MS = 2000
const CHECK_IN_POLL_MS = 25000

// Guards against submitting a recording that captured no speech. Whisper answers
// silence with confident filler rather than an empty string, so an unchecked
// clip becomes a wrong answer to the Question instead of a retry prompt.
// Measured against real clips: silence peaks near zero while speech peaks well
// above 0.1, even when the speaker is quiet or far from the microphone.
const SPEECH_PEAK_THRESHOLD = 0.04
const MIN_RECORDING_MS = 1000
const MIN_TRANSCRIPT_CHARS = 2

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

  const { voices, voice, setVoice } = useVoices(setError)
  const apiReady = useApiReady()
  const { evaluation, evaluating, resetEvaluation } = useEvaluation({ phase, sessionId, onError: setError })

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
      const resp = await fetch(api('/api/resume'), { method: 'POST', body: form })
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
      setResumeName('')
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

    // Whisper hallucinates on silence rather than returning nothing - a recording
    // that captured no speech comes back as confident filler ("Thank you.",
    // "Maybe, maybe, maybe."), which then gets submitted as the Candidate's
    // answer and derails the interview. So measure whether anyone actually
    // spoke, and refuse to send the clip if not.
    //
    // Peak amplitude is measured directly rather than inferred from blob size:
    // size depends on the browser's codec and bitrate, amplitude does not.
    const audioCtx = new AudioContext()
    const analyser = audioCtx.createAnalyser()
    analyser.fftSize = 2048
    audioCtx.createMediaStreamSource(stream).connect(analyser)
    const samples = new Uint8Array(analyser.fftSize)
    let peak = 0
    const levelTimer = setInterval(() => {
      analyser.getByteTimeDomainData(samples)
      for (let i = 0; i < samples.length; i++) {
        const amplitude = Math.abs(samples[i] - 128) / 128
        if (amplitude > peak) peak = amplitude
      }
    }, 100)
    const startedAt = Date.now()

    recorder.ondataavailable = (e) => chunks.push(e.data)
    recorder.onstop = async () => {
      clearInterval(levelTimer)
      audioCtx.close().catch(() => {})
      stream.getTracks().forEach((t) => t.stop())

      const heardSpeech = peak >= SPEECH_PEAK_THRESHOLD
      const longEnough = Date.now() - startedAt >= MIN_RECORDING_MS
      if (!heardSpeech || !longEnough) {
        setError(
          longEnough
            ? "I didn't catch that — check your microphone, or type your answer below."
            : "That recording was too short — hold it a moment longer, or type your answer below."
        )
        setStatus('idle')
        return
      }

      setStatus('transcribing')
      try {
        const blob = new Blob(chunks, { type: recorder.mimeType })
        const form = new FormData()
        form.append('file', blob, 'answer.webm')
        // Lets the backend prime Whisper with this Session's resume vocabulary
        // so names and project titles survive transcription (ADR 0026). The
        // digest stays server-side; only the id the client already has is sent.
        if (sessionId) form.append('session_id', sessionId)
        const resp = await fetch(api('/api/transcribe'), { method: 'POST', body: form })
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}))
          throw new Error(body.detail || `transcription failed (${resp.status})`)
        }
        const data = await resp.json()
        // Even with speech present Whisper can return nothing usable; submitting
        // that would answer the Question with noise.
        if (!data.transcript || data.transcript.trim().length < MIN_TRANSCRIPT_CHARS) {
          setError("I didn't catch that — try again, or type your answer below.")
          setStatus('idle')
          return
        }
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
