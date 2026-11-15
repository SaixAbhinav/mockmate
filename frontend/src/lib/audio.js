// Voice is best-effort (ADR 0036): the backend sends empty audio when speech
// synthesis fails, and the reply is already on screen as text. Neither that
// nor a browser that refuses to play should surface as an error.
export async function playAudio(audioB64, setStatus) {
  if (!audioB64) {
    setStatus('idle')
    return
  }
  setStatus('speaking')
  const audio = new Audio(`data:audio/mp3;base64,${audioB64}`)
  audio.onended = () => setStatus('idle')
  try {
    await audio.play()
  } catch {
    setStatus('idle')
  }
}
