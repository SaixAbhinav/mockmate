import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { playAudio } from '../lib/audio'
import { useSession } from './useSession'

vi.mock('../lib/audio', () => ({ playAudio: vi.fn() }))

const START = {
  session_id: 's1',
  first_question: 'Tell me about yourself.',
  question_number: 1,
  total_questions: 5,
  stage: 'intro',
  warm_up_source: 'resume',
  domain: 'ml_genai',
  audio_b64: '',
}

const DSA_PAYLOAD = {
  prompt: 'Implement running_sum.',
  function_name: 'running_sum',
  signature: 'def running_sum(nums):',
  starter_code: 'def running_sum(nums):\n    pass\n',
  test_cases: [],
}

function setup({ resumeId = null, apiReady = true } = {}) {
  const onError = vi.fn()
  const setStatus = vi.fn()
  const onNewQuestion = vi.fn()
  const onResetRound = vi.fn()
  const { result } = renderHook(() =>
    useSession({ voice: 'v1', resumeId, apiReady, setStatus, onError, onNewQuestion, onResetRound })
  )
  return { result, onError, setStatus, onNewQuestion, onResetRound }
}

async function startSession(result) {
  await act(async () => {
    await result.current.startInterview()
  })
}

describe('useSession', () => {
  let mocks
  beforeEach(() => {
    mocks = installMocks()
    playAudio.mockClear()
  })

  it('sends the uploaded résumé id when starting an interview', async () => {
    mocks.respond('/api/session', START)
    const { result } = setup({ resumeId: 'r1' })

    await startSession(result)

    const call = mocks.calls.find((c) => c.path.endsWith('/api/session'))
    expect(JSON.parse(call.init.body)).toMatchObject({ resume_id: 'r1', allow_bank_fallback: false })
    expect(result.current.screen).toBe('interview')
    expect(result.current.warmUpSource).toBe('resume')
  })

  it('treats a 409 as a fallback offer, not an error (ADR 0023)', async () => {
    mocks.respond('/api/session', { detail: { message: 'Could not tailor an interview.' } }, false, 409)
    const { result, onError } = setup({ resumeId: 'r1' })

    await startSession(result)

    expect(result.current.fallbackOffer).toEqual({ message: 'Could not tailor an interview.' })
    expect(result.current.screen).toBe('start')
    expect(onError).not.toHaveBeenCalledWith(expect.stringContaining('409'))
  })

  it('accepting the offer retries with allow_bank_fallback and clears it', async () => {
    mocks.respond('/api/session', { detail: { message: 'nope' } }, false, 409)
    const { result } = setup({ resumeId: 'r1' })
    await startSession(result)
    expect(result.current.fallbackOffer).not.toBeNull()

    mocks.respond('/api/session', { ...START, warm_up_source: 'bank' })
    await act(async () => {
      await result.current.startInterview(true)
    })

    const retry = mocks.calls.filter((c) => c.path.endsWith('/api/session')).at(-1)
    expect(JSON.parse(retry.init.body).allow_bank_fallback).toBe(true)
    expect(result.current.fallbackOffer).toBeNull()
    expect(result.current.screen).toBe('interview')
  })

  it('blames the waking container when the very first start fails', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error('connection refused')
    })
    const { result, onError } = setup({ apiReady: false })

    await startSession(result)

    expect(onError).toHaveBeenCalledWith(expect.stringContaining('still waking up'))
  })

  it('records the reply, the progress and the turn latency on a successful answer', async () => {
    mocks.respond('/api/session', START)
    const { result } = setup()
    await startSession(result)

    mocks.respond('/api/session/s1/answer', {
      reply: 'Good — tell me more about the evaluation harness.',
      phase: 'probing',
      stage: 'warm_up',
      question_number: 2,
      total_questions: 5,
      audio_b64: '',
    })
    await act(async () => {
      await result.current.sendTranscript('I work on retrieval systems.')
    })

    expect(result.current.history).toEqual([
      { role: 'assistant', content: 'Tell me about yourself.' },
      { role: 'user', content: 'I work on retrieval systems.' },
      { role: 'assistant', content: 'Good — tell me more about the evaluation harness.' },
    ])
    expect(result.current.phase).toBe('probing')
    expect(result.current.stage).toBe('warm_up')
    expect(result.current.questionNumber).toBe(2)
    expect(typeof result.current.latencyMs).toBe('number')
    expect(playAudio).toHaveBeenCalled()
  })

  it('ignores an empty answer', async () => {
    mocks.respond('/api/session', START)
    const { result } = setup()
    await startSession(result)

    await act(async () => {
      await result.current.sendTranscript('   ')
    })

    expect(mocks.calls.filter((c) => c.path.includes('/answer'))).toHaveLength(0)
  })

  it('hands the coding round its cue when a new question arrives', async () => {
    mocks.respond('/api/session', START)
    const { result, onNewQuestion } = setup()
    await startSession(result)

    mocks.respond('/api/session/s1/answer', {
      reply: "Let's write some code.",
      phase: 'advancing',
      stage: 'dsa',
      question_number: 4,
      total_questions: 5,
      dsa: DSA_PAYLOAD,
      audio_b64: '',
    })
    await act(async () => {
      await result.current.sendTranscript('done talking')
    })

    expect(onNewQuestion).toHaveBeenCalledWith(DSA_PAYLOAD)
    expect(result.current.dsa).toEqual(DSA_PAYLOAD)
  })

  it('does not reset the editor when a coding chat echoes the same question (ADR 0019)', async () => {
    mocks.respond('/api/session', START)
    const { result, onNewQuestion } = setup()
    await startSession(result)

    const answer = {
      reply: "Let's write some code.",
      phase: 'advancing',
      stage: 'dsa',
      question_number: 4,
      total_questions: 5,
      dsa: DSA_PAYLOAD,
      audio_b64: '',
    }
    mocks.respond('/api/session/s1/answer', answer)
    await act(async () => {
      await result.current.sendTranscript('done talking')
    })
    expect(onNewQuestion).toHaveBeenCalledTimes(1)

    // A side conversation during the round carries the same question's payload;
    // treating it as new would wipe the Candidate's code mid-question.
    mocks.respond('/api/session/s1/answer', { ...answer, reply: 'Yes, the list can be empty.' })
    await act(async () => {
      await result.current.sendTranscript('Can the input be empty?')
    })

    expect(onNewQuestion).toHaveBeenCalledTimes(1)
  })

  it('moves the interview on without touching the editor on submit', async () => {
    mocks.respond('/api/session', START)
    const { result, onNewQuestion } = setup()
    await startSession(result)

    act(() => {
      result.current.applySubmitProgress({
        phase: 'advancing',
        stage: 'dsa',
        question_number: 5,
        total_questions: 5,
      })
    })

    expect(result.current.questionNumber).toBe(5)
    expect(onNewQuestion).not.toHaveBeenCalled()
  })

  it('returns to the start screen and resets the round on a new interview', async () => {
    mocks.respond('/api/session', START)
    const { result, onResetRound } = setup()
    await startSession(result)

    act(() => result.current.startNewInterview())

    expect(result.current.screen).toBe('start')
    expect(result.current.sessionId).toBeNull()
    expect(result.current.history).toEqual([])
    expect(result.current.dsa).toBeNull()
    expect(result.current.sessionDomain).toBeNull()
    expect(onResetRound).toHaveBeenCalled()
  })

  it('rolls the optimistic turn back when the answer fails', async () => {
    mocks.respond('/api/session', START)
    const { result, onError } = setup()
    await startSession(result)

    mocks.respond('/api/session/s1/answer', {}, false, 500)
    await act(async () => {
      await result.current.sendTranscript('my answer')
    })

    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining('500')))
    expect(result.current.history).toEqual([
      { role: 'assistant', content: 'Tell me about yourself.' },
    ])
  })
})
