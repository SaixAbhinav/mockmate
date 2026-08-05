import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { useApiReady } from './useApiReady'

describe('useApiReady', () => {
  let mocks
  beforeEach(() => {
    mocks = installMocks()
  })

  it('reports ready once the health ping answers 2xx', async () => {
    mocks.respond('/api/health', { status: 'ok' })
    const { result } = renderHook(() => useApiReady())

    await waitFor(() => expect(result.current).toBe(true))
  })

  it('stays not-ready on a 503 from a container that is still starting', async () => {
    // fetch() resolves for 5xx, so a plain .then() would clear the waking
    // notice on exactly the response that means "still waking" (ADR 0025).
    mocks.respond('/api/health', {}, false, 503)
    const { result } = renderHook(() => useApiReady())

    await waitFor(() => expect(mocks.calls.some((c) => c.path.includes('/api/health'))).toBe(true))
    expect(result.current).toBe(false)
  })

  it('stays not-ready when the ping cannot connect at all', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error('connection refused')
    })
    const { result } = renderHook(() => useApiReady())

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(result.current).toBe(false)
  })
})
