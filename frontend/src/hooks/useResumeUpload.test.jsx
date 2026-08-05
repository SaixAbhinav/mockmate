import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { useResumeUpload } from './useResumeUpload'

function changeEvent(name) {
  return { target: { files: [new File(['cv'], name, { type: 'application/pdf' })] } }
}

function setup() {
  const onError = vi.fn()
  const { result } = renderHook(() => useResumeUpload({ onError }))
  return { result, onError }
}

describe('useResumeUpload', () => {
  let mocks
  beforeEach(() => {
    mocks = installMocks()
  })

  it('ignores a change event with no file', async () => {
    const { result } = setup()

    await act(async () => {
      await result.current.handleResumeChange({ target: { files: [] } })
    })

    expect(result.current.resumeStatus).toBe('none')
    expect(mocks.calls).toHaveLength(0)
  })

  it('keeps the id and the filename once the upload succeeds', async () => {
    mocks.respond('/api/resume', { resume_id: 'r1' })
    const { result, onError } = setup()

    await act(async () => {
      await result.current.handleResumeChange(changeEvent('cv.pdf'))
    })

    expect(result.current.resumeId).toBe('r1')
    expect(result.current.resumeName).toBe('cv.pdf')
    expect(result.current.resumeStatus).toBe('ready')
    expect(onError).toHaveBeenCalledWith(null)
  })

  it('reports the backend detail and keeps no filename when the upload fails', async () => {
    mocks.respond('/api/resume', { detail: 'that PDF has no extractable text' }, false, 400)
    const { result, onError } = setup()

    await act(async () => {
      await result.current.handleResumeChange(changeEvent('scan.pdf'))
    })

    expect(result.current.resumeStatus).toBe('failed')
    expect(result.current.resumeId).toBeNull()
    // No filename in the failed state - showing one implies a file is loaded.
    expect(result.current.resumeName).toBe('')
    expect(onError).toHaveBeenCalledWith(
      expect.stringContaining('that PDF has no extractable text')
    )
  })

  it('lets a faster second upload win over a slow first one', async () => {
    const { result } = setup()

    // Hold the first upload open, let the second one through, then release the
    // first: without the supersede token the stale reply would land last and
    // overwrite the résumé the Candidate actually chose.
    let releaseFirst
    const firstInFlight = new Promise((resolve) => {
      releaseFirst = resolve
    })
    let call = 0
    globalThis.fetch = vi.fn(async () => {
      call += 1
      if (call === 1) {
        await firstInFlight
        return { ok: true, status: 200, json: async () => ({ resume_id: 'slow' }) }
      }
      return { ok: true, status: 200, json: async () => ({ resume_id: 'fast' }) }
    })

    let firstDone
    act(() => {
      firstDone = result.current.handleResumeChange(changeEvent('slow.pdf'))
    })
    await act(async () => {
      await result.current.handleResumeChange(changeEvent('fast.pdf'))
    })

    expect(result.current.resumeId).toBe('fast')

    await act(async () => {
      releaseFirst()
      await firstDone
    })

    expect(result.current.resumeId).toBe('fast')
    expect(result.current.resumeName).toBe('fast.pdf')
    expect(result.current.resumeStatus).toBe('ready')
  })

  it('does not let a superseded upload fail the one that replaced it', async () => {
    const { result, onError } = setup()

    let failFirst
    const firstInFlight = new Promise((resolve) => {
      failFirst = resolve
    })
    let call = 0
    globalThis.fetch = vi.fn(async () => {
      call += 1
      if (call === 1) {
        await firstInFlight
        throw new Error('network died')
      }
      return { ok: true, status: 200, json: async () => ({ resume_id: 'fast' }) }
    })

    let firstDone
    act(() => {
      firstDone = result.current.handleResumeChange(changeEvent('slow.pdf'))
    })
    await act(async () => {
      await result.current.handleResumeChange(changeEvent('fast.pdf'))
    })

    await act(async () => {
      failFirst()
      await firstDone
    })

    await waitFor(() => expect(result.current.resumeStatus).toBe('ready'))
    expect(result.current.resumeId).toBe('fast')
    expect(onError).not.toHaveBeenCalledWith(expect.stringContaining('network died'))
  })
})
