import { useEffect, useState } from 'react'
import { api } from '../api'

// A free-tier API container sleeps when idle and takes ~30-60s to wake
// (ADR 0025). Ping it as soon as the start screen renders so it boots while
// the Candidate reads and picks a resume, not after they click Start.
//
// Deliberately no timeout: aborting would kill a request that was going to
// succeed. The wait is fine; leaving the Candidate to guess is not, so the
// result is tracked and shown.
//
// Only a 2xx counts as awake. fetch() resolves for 5xx as well, so a plain
// .then() would clear the notice on the 502/503 a platform serves *while*
// the container is still starting - exactly when the notice is wanted. A
// failure leaves the notice up, which reads as "still waking" and is the
// honest thing to show when the API is not answering.
export function useApiReady() {
  const [apiReady, setApiReady] = useState(false)

  useEffect(() => {
    fetch(api('/api/health'))
      .then((r) => {
        if (r.ok) setApiReady(true)
      })
      .catch(() => {})
  }, [])

  return apiReady
}
