export async function playAudio(audioB64, setStatus) {
  setStatus('speaking')
  const audio = new Audio(`data:audio/mp3;base64,${audioB64}`)
  audio.onended = () => setStatus('idle')
  await audio.play()
}
