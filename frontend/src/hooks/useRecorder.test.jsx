import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { useRecorder } from './useRecorder'

function setup({ peak }) {
  const mocks = installMocks({ peak })
  const onTranscript = vi.fn()
  const onError = vi.fn()
  const setStatus = vi.fn()
  const { result } = renderHook(() =>
    useRecorder({ sessionId: 's1', setStatus, onError, onTranscript })
  )
  return { mocks, onTranscript, onError, setStatus, result }
}

// startRecording clears any stale banner first, so the message is the last
// non-null call, not the first.
const lastError = (onError) =>
  onError.mock.calls.map((c) => c[0]).filter(Boolean).at(-1)

describe('useRecorder', () => {
  beforeEach(() => vi.useRealTimers())

  it('refuses a clip that captured no speech', async () => {
    const { mocks, onTranscript, onError, result } = setup({ peak: 0 })
    mocks.respond('/api/transcribe', { transcript: 'Thank you.' })
    await act(async () => {
      await result.current.startRecording()
    })
    await new Promise((r) => setTimeout(r, 1100))
    await act(async () => {
      result.current.stopRecording()
    })
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(lastError(onError)).toMatch(/didn't catch that/i)
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('refuses a clip that was too short even when speech was heard', async () => {
    const { onTranscript, onError, result } = setup({ peak: 0.5 })
    await act(async () => {
      await result.current.startRecording()
    })
    await act(async () => {
      result.current.stopRecording()
    })
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(lastError(onError)).toMatch(/too short/i)
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('sends a clip that had speech and lasted long enough', async () => {
    const { mocks, onTranscript, result } = setup({ peak: 0.5 })
    mocks.respond('/api/transcribe', { transcript: 'a real answer' })
    await act(async () => {
      await result.current.startRecording()
    })
    await new Promise((r) => setTimeout(r, 1100))
    await act(async () => {
      result.current.stopRecording()
    })
    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith('a real answer'))
  })

  it('reports a permission refusal without starting a recording', async () => {
    const { onError, setStatus, result } = setup({ peak: 0.5 })
    globalThis.navigator.mediaDevices.getUserMedia = vi.fn(async () => {
      throw new Error('denied')
    })
    await act(async () => {
      await result.current.startRecording()
    })
    expect(lastError(onError)).toMatch(/microphone permission denied/i)
    expect(setStatus).not.toHaveBeenCalledWith('recording')
  })
})
