import { useRef } from 'react'
import { api } from '../api'

// Guards against submitting a recording that captured no speech. Whisper answers
// silence with confident filler rather than an empty string, so an unchecked
// clip becomes a wrong answer to the Question instead of a retry prompt.
// Measured against real clips: silence peaks near zero while speech peaks well
// above 0.1, even when the speaker is quiet or far from the microphone.
const SPEECH_PEAK_THRESHOLD = 0.04
const MIN_RECORDING_MS = 1000
const MIN_TRANSCRIPT_CHARS = 2

export function useRecorder({ sessionId, setStatus, onError, onTranscript }) {
  const recorderRef = useRef(null)

  async function startRecording() {
    onError(null)
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      onError('Microphone permission denied — allow it in the address bar, or type below.')
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
        onError(
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
          onError("I didn't catch that — try again, or type your answer below.")
          setStatus('idle')
          return
        }
        onTranscript(data.transcript)
      } catch (err) {
        onError(String(err))
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

  return { startRecording, stopRecording }
}
