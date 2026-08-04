import { useState } from 'react'
import { api } from '../api'
import { playAudio } from '../lib/audio'

// Owns the Session: starting one, the transcript, and the progress a backend
// reply reports (phase, stage, question number, dsa payload).
// `onNewQuestion` / `onResetRound` hand the coding round its cue: the editor
// state lives in `useDsaRound`, but only this hook knows when a payload belongs
// to a new Question (ADR 0019) or when the Session has been torn down.
export function useSession({
  voice,
  resumeId,
  apiReady,
  setStatus,
  onError,
  onNewQuestion,
  onResetRound,
}) {
  const [screen, setScreen] = useState('start') // start | interview
  const [sessionDomain, setSessionDomain] = useState(null) // derived label (ADR 0023)
  const [fallbackOffer, setFallbackOffer] = useState(null) // 409 detail, or null
  const [sessionId, setSessionId] = useState(null)
  const [history, setHistory] = useState([])
  const [phase, setPhase] = useState(null) // null | advancing | probing | clarifying | done
  const [questionNumber, setQuestionNumber] = useState(null)
  const [totalQuestions, setTotalQuestions] = useState(null)
  const [latencyMs, setLatencyMs] = useState(null)
  const [stage, setStage] = useState(null) // intro | warm_up | done
  const [warmUpSource, setWarmUpSource] = useState(null) // resume | bank
  const [dsa, setDsa] = useState(null) // DsaPayload for the current coding question

  function appendAssistant(content) {
    setHistory((h) => [...h, { role: 'assistant', content }])
  }

  async function startInterview(allowBankFallback = false) {
    onError(null)
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
      onError(
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
    onError(null)
    setStatus('idle')
    setStage(null)
    setWarmUpSource(null)
    setDsa(null)
    onResetRound()
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
      onNewQuestion(payload)
    }
    setQuestionNumber(data.question_number)
    setTotalQuestions(data.total_questions)
  }

  // A submit reply reports progress but carries no dsa payload, so it moves the
  // interview on without touching the editor. Submits must use this (not
  // `applyProgress`): `applyProgress` sets `dsa` from `data.dsa ?? null`, and a
  // submit reply has no `dsa`, so routing it through `applyProgress` would null
  // out `dsa` and reset `dsaSubmitted`, putting the editor back on screen after
  // the Candidate already submitted.
  function applySubmitProgress(data) {
    setPhase(data.phase)
    setQuestionNumber(data.question_number)
    setTotalQuestions(data.total_questions)
    setStage(data.stage)
  }

  async function sendTranscript(transcript) {
    const text = transcript.trim()
    if (!text || !sessionId) return
    const newHistory = [...history, { role: 'user', content: text }]
    setHistory(newHistory)
    setStatus('thinking')
    onError(null)
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
      onError(String(err))
      setStatus('idle')
    }
  }

  return {
    screen,
    sessionId,
    history,
    phase,
    stage,
    questionNumber,
    totalQuestions,
    sessionDomain,
    warmUpSource,
    fallbackOffer,
    setFallbackOffer,
    latencyMs,
    dsa,
    startInterview,
    startNewInterview,
    sendTranscript,
    applySubmitProgress,
    appendAssistant,
  }
}
