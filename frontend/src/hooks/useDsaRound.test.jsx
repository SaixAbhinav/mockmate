import { act, renderHook, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { playAudio } from '../lib/audio'
import { useDsaRound } from './useDsaRound'

vi.mock('../lib/audio', () => ({ playAudio: vi.fn() }))

const dsa = {
  function_name: 'two_sum',
  signature: 'def two_sum(nums, target):',
  starter_code: 'def two_sum(nums, target):\n    pass\n',
  test_cases: [],
}

function setup() {
  const statusRef = createRef()
  statusRef.current = 'idle'
  const appendAssistant = vi.fn()
  const applySubmitProgress = vi.fn()
  const setStatus = vi.fn()
  const onError = vi.fn()
  const { result } = renderHook(() =>
    useDsaRound({
      sessionId: 's1',
      voice: 'v1',
      dsa,
      statusRef,
      setStatus,
      onError,
      appendAssistant,
      applySubmitProgress,
    })
  )
  return { result, appendAssistant, applySubmitProgress, setStatus, onError, statusRef }
}

describe('useDsaRound', () => {
  let mocks
  beforeEach(() => {
    vi.useFakeTimers()
    mocks = installMocks()
    playAudio.mockClear()
  })

  it('does not snapshot untouched starter code', async () => {
    setup()
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    const snapshots = mocks.calls.filter((c) => c.path.includes('/dsa/snapshot'))
    expect(snapshots).toHaveLength(0)
  })

  it('snapshots once the Candidate has actually typed', async () => {
    mocks.respond('/dsa/snapshot', {})
    const { result } = setup()
    act(() => {
      result.current.setCode(dsa.starter_code + '    return []\n')
    })
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })
    const snapshots = mocks.calls.filter((c) => c.path.includes('/dsa/snapshot'))
    expect(snapshots).toHaveLength(1)
  })

  it('adds no turn when the interviewer stays silent', async () => {
    mocks.respond('/dsa/check-in', { action: 'silent' })
    const { appendAssistant } = setup()
    await act(async () => {
      vi.advanceTimersByTime(26000)
    })
    expect(appendAssistant).not.toHaveBeenCalled()
  })

  it('adds a turn when the interviewer checks in', async () => {
    mocks.respond('/dsa/check-in', { action: 'nudge', remark: 'How is it going?', audio_b64: '' })
    const { appendAssistant } = setup()
    await act(async () => {
      vi.advanceTimersByTime(26000)
    })
    await waitFor(() => expect(appendAssistant).toHaveBeenCalledWith('How is it going?'))
  })

  it('does not poll while the Candidate is speaking', async () => {
    mocks.respond('/dsa/check-in', { action: 'nudge', remark: 'x', audio_b64: '' })
    const { statusRef, appendAssistant } = setup()
    statusRef.current = 'recording'
    await act(async () => {
      vi.advanceTimersByTime(26000)
    })
    expect(appendAssistant).not.toHaveBeenCalled()
  })

  it('adds the transcript turn but does not play audio if the Candidate starts speaking while a check-in is in flight', async () => {
    mocks.respond('/dsa/check-in', { action: 'nudge', remark: 'still there?', audio_b64: 'abc' })
    const { statusRef, appendAssistant } = setup()

    // Defer the check-in response so we can flip statusRef mid-flight, after
    // the request has gone out but before its reply is handled.
    const originalFetch = globalThis.fetch
    let resolveGate
    const gate = new Promise((resolve) => {
      resolveGate = resolve
    })
    globalThis.fetch = vi.fn(async (url, init) => {
      if (String(url).includes('/dsa/check-in')) {
        await gate
      }
      return originalFetch(url, init)
    })

    // Fire the poll: this issues the request and parks it on `gate`.
    act(() => {
      vi.advanceTimersByTime(25000)
    })

    // The Candidate starts speaking while the request is still in flight.
    statusRef.current = 'recording'
    resolveGate()

    globalThis.fetch = originalFetch

    await waitFor(() => expect(appendAssistant).toHaveBeenCalledWith('still there?'))
    expect(playAudio).not.toHaveBeenCalled()
  })

  it('wires submitCode through to applySubmitProgress, appendAssistant, and dsaSubmitted', async () => {
    const submitBody = {
      run: { passed: true },
      reply: 'Nice work on that one.',
      phase: 'coding',
      question_number: 2,
      total_questions: 2,
      stage: 'submitted',
      audio_b64: 'xyz',
    }
    mocks.respond('/dsa/submit', submitBody)
    const { result, appendAssistant, applySubmitProgress } = setup()

    await act(async () => {
      await result.current.submitCode()
    })

    expect(applySubmitProgress).toHaveBeenCalledWith(submitBody)
    expect(appendAssistant).toHaveBeenCalledWith('Nice work on that one.')
    expect(result.current.dsaSubmitted).toBe(true)
  })
})
