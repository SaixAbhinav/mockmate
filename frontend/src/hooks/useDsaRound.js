import { useEffect, useState } from 'react'
import { api } from '../api'
import { playAudio } from '../lib/audio'

// The watching interviewer (ADR 0018): snapshot on a typing pause; poll for
// check-ins. The backend owns the real policy (offer, interval, cooldowns,
// cap) - the frontend just asks often and usually hears "silent".
const SNAPSHOT_DEBOUNCE_MS = 2000
const CHECK_IN_POLL_MS = 25000

// Owns the coding round's editor state: the code, the run report, and whether
// this Question has been submitted.
export function useDsaRound({
  sessionId,
  voice,
  dsa,
  statusRef,
  setStatus,
  onError,
  appendAssistant,
  applySubmitProgress,
}) {
  const [code, setCode] = useState(dsa?.starter_code ?? '')
  const [runReport, setRunReport] = useState(null)
  const [dsaSubmitted, setDsaSubmitted] = useState(false)
  const [running, setRunning] = useState(false)

  // Called only when `applyProgress` sees a payload for a *different* question
  // (ADR 0019) - a coding-chat reply carries the same question's payload, and
  // resetting on that would wipe the Candidate's code mid-question.
  function startQuestion(payload) {
    setCode(payload.starter_code)
    setRunReport(null)
    setDsaSubmitted(false)
  }

  function resetDsaRound() {
    setCode('')
    setRunReport(null)
    setDsaSubmitted(false)
  }

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
        appendAssistant(data.remark)
        if (statusRef.current === 'idle') {
          await playAudio(data.audio_b64, setStatus)
        }
      } catch {
        // a failed check-in is a silent one
      }
    }, CHECK_IN_POLL_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dsa, dsaSubmitted, sessionId, voice])

  async function runCode() {
    setRunning(true)
    onError(null)
    try {
      const resp = await fetch(api(`/api/session/${sessionId}/dsa/run`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
      if (!resp.ok) throw new Error(`run failed (${resp.status})`)
      setRunReport(await resp.json())
    } catch (err) {
      onError(String(err))
    } finally {
      setRunning(false)
    }
  }

  async function submitCode() {
    setStatus('thinking')
    onError(null)
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
      appendAssistant(data.reply)
      applySubmitProgress(data)
      await playAudio(data.audio_b64, setStatus)
    } catch (err) {
      onError(String(err))
      setStatus('idle')
    }
  }

  return {
    code,
    setCode,
    runReport,
    dsaSubmitted,
    running,
    runCode,
    submitCode,
    startQuestion,
    resetDsaRound,
  }
}
