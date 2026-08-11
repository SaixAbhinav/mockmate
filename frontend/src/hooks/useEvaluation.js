import { useEffect, useState } from 'react'
import { api } from '../api'

// The Evaluation only exists once the Session is done.
export function useEvaluation({ phase, sessionId, onError }) {
  const [evaluation, setEvaluation] = useState(null)
  const [evaluating, setEvaluating] = useState(false)

  useEffect(() => {
    if (phase !== 'done' || !sessionId) return
    const controller = new AbortController()
    setEvaluating(true)
    fetch(api(`/api/session/${sessionId}/evaluation`), { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`evaluation failed (${r.status})`)
        return r.json()
      })
      .then(setEvaluation)
      .catch((err) => {
        if (err.name !== 'AbortError') onError(String(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setEvaluating(false)
      })
    return () => controller.abort()
    // Deps are deliberately narrow: onError is a stable callback read via
    // closure, not a value whose change should re-fetch the Evaluation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, sessionId])

  function resetEvaluation() {
    setEvaluation(null)
    setEvaluating(false)
  }

  return { evaluation, evaluating, resetEvaluation }
}
