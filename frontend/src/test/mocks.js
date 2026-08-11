import { vi } from 'vitest'

// jsdom has none of these. The recorder fake is driven manually so a test can
// decide what "the Candidate spoke" or "silence" sounds like (ADR-free, but
// see the speech-peak gate in useRecorder).
export function installMocks({ peak = 0.5 } = {}) {
  const routes = new Map()
  const calls = []

  const respond = (path, body, ok = true, status = 200) =>
    routes.set(path, { body, ok, status })

  globalThis.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url)
    calls.push({ path, init })
    const match = [...routes.keys()].find((k) => path.endsWith(k))
    if (!match) throw new Error(`no mock for ${path}`)
    const { body, ok, status } = routes.get(match)
    return { ok, status, json: async () => body }
  })

  let recorderInstance = null
  class FakeMediaRecorder {
    constructor() {
      this.mimeType = 'audio/webm'
      recorderInstance = this
    }
    start() {}
    stop() {
      this.ondataavailable?.({ data: new Blob(['x']) })
      this.onstop?.()
    }
  }
  globalThis.MediaRecorder = FakeMediaRecorder

  globalThis.navigator.mediaDevices = {
    getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop() {} }] })),
  }

  // getByteTimeDomainData writes samples centred on 128; the app derives peak
  // amplitude as |sample - 128| / 128, so this yields exactly `peak`.
  class FakeAudioContext {
    createAnalyser() {
      return {
        fftSize: 2048,
        getByteTimeDomainData(arr) {
          arr.fill(128 + Math.round(peak * 128))
        },
      }
    }
    createMediaStreamSource() {
      return { connect() {} }
    }
    async close() {}
  }
  globalThis.AudioContext = FakeAudioContext

  globalThis.Audio = class {
    play() {
      this.onended?.()
      return Promise.resolve()
    }
  }

  globalThis.HTMLElement.prototype.scrollIntoView = vi.fn()

  return { respond, calls, recorder: () => recorderInstance }
}
