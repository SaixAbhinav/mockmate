import { useEffect, useState } from 'react'
import { api } from '../api'

export function useVoices(onError) {
  const [voices, setVoices] = useState({})
  const [voice, setVoice] = useState('')

  useEffect(() => {
    fetch(api('/api/voices'))
      .then((r) => r.json())
      .then((data) => {
        setVoices(data.voices)
        setVoice(data.default)
      })
      .catch(() => onError('backend not reachable — is it running on port 8000?'))
    // Deps are deliberately empty: onError is a stable callback read via
    // closure, and this fetch is meant to run once on mount, not on rerenders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { voices, voice, setVoice }
}
