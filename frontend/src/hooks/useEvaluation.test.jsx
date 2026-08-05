import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { useEvaluation } from './useEvaluation'

const evaluation = { overall: { assessment: 'Solid' }, warm_up: {}, dsa: {} }

describe('useEvaluation', () => {
  let mocks
  beforeEach(() => {
    mocks = installMocks()
  })

  it('does not fetch before the Session is done', async () => {
    const onError = vi.fn()
    renderHook(() => useEvaluation({ phase: 'probing', sessionId: 's1', onError }))

    expect(mocks.calls.filter((c) => c.path.includes('/evaluation'))).toHaveLength(0)
  })

  it('does not fetch without a Session id', async () => {
    const onError = vi.fn()
    renderHook(() => useEvaluation({ phase: 'done', sessionId: null, onError }))

    expect(mocks.calls.filter((c) => c.path.includes('/evaluation'))).toHaveLength(0)
  })

  it('fetches the scorecard when the interview reaches done', async () => {
    mocks.respond('/evaluation', evaluation)
    const onError = vi.fn()
    const { result } = renderHook(() =>
      useEvaluation({ phase: 'done', sessionId: 's1', onError })
    )

    await waitFor(() => expect(result.current.evaluation).toEqual(evaluation))
    expect(result.current.evaluating).toBe(false)
    expect(onError).not.toHaveBeenCalled()
  })

  it('fetches once the phase flips to done, not on mount', async () => {
    mocks.respond('/evaluation', evaluation)
    const onError = vi.fn()
    const { result, rerender } = renderHook(
      ({ phase }) => useEvaluation({ phase, sessionId: 's1', onError }),
      { initialProps: { phase: 'probing' } }
    )
    expect(result.current.evaluation).toBeNull()

    rerender({ phase: 'done' })

    await waitFor(() => expect(result.current.evaluation).toEqual(evaluation))
  })

  it('surfaces a failed scoring request and stops the pending state', async () => {
    mocks.respond('/evaluation', {}, false, 500)
    const onError = vi.fn()
    const { result } = renderHook(() =>
      useEvaluation({ phase: 'done', sessionId: 's1', onError })
    )

    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining('500')))
    expect(result.current.evaluating).toBe(false)
  })

  it('clears the scorecard on reset, so a second interview starts blank', async () => {
    mocks.respond('/evaluation', evaluation)
    const onError = vi.fn()
    const { result } = renderHook(() =>
      useEvaluation({ phase: 'done', sessionId: 's1', onError })
    )
    await waitFor(() => expect(result.current.evaluation).toEqual(evaluation))

    act(() => result.current.resetEvaluation())

    expect(result.current.evaluation).toBeNull()
    expect(result.current.evaluating).toBe(false)
  })

  it('does not report an abort as an error when the Session unmounts mid-fetch', async () => {
    const onError = vi.fn()
    globalThis.fetch = vi.fn(
      (url, { signal } = {}) =>
        new Promise((_, reject) => {
          signal?.addEventListener('abort', () => {
            const err = new Error('aborted')
            err.name = 'AbortError'
            reject(err)
          })
        })
    )
    const { unmount } = renderHook(() =>
      useEvaluation({ phase: 'done', sessionId: 's1', onError })
    )

    unmount()

    await waitFor(() => expect(onError).not.toHaveBeenCalled())
  })
})
