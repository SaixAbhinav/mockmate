import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { useVoices } from './useVoices'

describe('useVoices', () => {
  let mocks
  beforeEach(() => {
    mocks = installMocks()
  })

  it('loads the catalogue and selects the backend default', async () => {
    mocks.respond('/api/voices', { voices: { v1: 'Voice One', v2: 'Voice Two' }, default: 'v2' })
    const onError = vi.fn()
    const { result } = renderHook(() => useVoices(onError))

    await waitFor(() => expect(result.current.voice).toBe('v2'))
    expect(result.current.voices).toEqual({ v1: 'Voice One', v2: 'Voice Two' })
    expect(onError).not.toHaveBeenCalled()
  })

  it('says the backend is unreachable rather than printing the exception', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error('connection refused')
    })
    const onError = vi.fn()
    renderHook(() => useVoices(onError))

    await waitFor(() =>
      expect(onError).toHaveBeenCalledWith(expect.stringContaining('backend not reachable'))
    )
  })

  it('keeps the Candidate’s choice once they pick a voice', async () => {
    mocks.respond('/api/voices', { voices: { v1: 'Voice One', v2: 'Voice Two' }, default: 'v1' })
    const { result } = renderHook(() => useVoices(vi.fn()))
    await waitFor(() => expect(result.current.voice).toBe('v1'))

    act(() => result.current.setVoice('v2'))

    expect(result.current.voice).toBe('v2')
  })
})
