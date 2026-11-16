import { afterEach, describe, expect, it, vi } from 'vitest'
import { playAudio } from './audio'

describe('playAudio', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('speaks the reply and goes idle when it ends', async () => {
    const created = []
    vi.stubGlobal('Audio', class {
      constructor(src) { this.src = src; created.push(this) }
      play() { this.onended?.(); return Promise.resolve() }
    })
    const setStatus = vi.fn()

    await playAudio('bXAz', setStatus)

    expect(created[0].src).toBe('data:audio/mp3;base64,bXAz')
    expect(setStatus.mock.calls.map((c) => c[0])).toEqual(['speaking', 'idle'])
  })

  it('stays silent when the reply came back without audio (ADR 0036)', async () => {
    const AudioSpy = vi.fn()
    vi.stubGlobal('Audio', AudioSpy)
    const setStatus = vi.fn()

    await playAudio('', setStatus)

    expect(AudioSpy).not.toHaveBeenCalled()
    expect(setStatus).toHaveBeenCalledWith('idle')
    expect(setStatus).not.toHaveBeenCalledWith('speaking')
  })

  it('treats a playback failure as silence, not an error', async () => {
    vi.stubGlobal('Audio', class {
      play() { return Promise.reject(new Error('NotSupportedError: no supported source')) }
    })
    const setStatus = vi.fn()

    await expect(playAudio('bXAz', setStatus)).resolves.toBeUndefined()

    expect(setStatus).toHaveBeenLastCalledWith('idle')
  })
})
