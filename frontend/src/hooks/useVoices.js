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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { voices, voice, setVoice }
}
