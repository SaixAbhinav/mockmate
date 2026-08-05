import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from './test/mocks'
import App from './App'

// CodeMirror needs layout APIs jsdom does not have, and no assertion here is
// about the editor itself.
vi.mock('@uiw/react-codemirror', () => ({
  default: ({ value }) => <textarea readOnly value={value} aria-label="editor" />,
}))

function baseRoutes(mocks) {
  mocks.respond('/api/voices', { voices: { v1: 'Voice One' }, default: 'v1' })
  mocks.respond('/api/health', { status: 'ok' })
}

const START = {
  session_id: 's1',
  first_question: 'Tell me about yourself.',
  question_number: 1,
  total_questions: 5,
  stage: 'intro',
  warm_up_source: 'bank',
  domain: 'ml_genai',
  audio_b64: '',
}

const DSA_PAYLOAD = {
  prompt: 'Implement running_sum: return the running total at each index.',
  function_name: 'running_sum',
  signature: 'def running_sum(nums):',
  starter_code: 'def running_sum(nums):\n    pass\n',
  test_cases: [],
}

const EVALUATION = {
  assessment: 'A solid interview overall.',
  coverage: { answered: 3, total: 3 },
  averages: { correctness: 4 },
  strengths: ['Clear structure'],
  improvements: ['Give more concrete numbers'],
  questions: [{ question: 'Tell me about yourself.', correctness: 4, depth: 3, clarity: 4, comment: 'Good.' }],
  dsa: null,
}

async function startInterview(mocks) {
  mocks.respond('/api/session', START)
  render(<App />)
  await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
  await screen.findByText('Tell me about yourself.')
}

async function uploadResume(mocks, name = 'cv.pdf') {
  mocks.respond('/api/resume', { resume_id: 'r1' })
  const { container } = render(<App />)
  await screen.findByText('Sit the interview before it counts.')
  const input = container.querySelector('input[type="file"]')
  await userEvent.upload(input, new File(['cv'], name, { type: 'application/pdf' }))
  await screen.findByText(name)
  return container
}

describe('App', () => {
  let mocks
  beforeEach(() => {
    mocks = installMocks()
    baseRoutes(mocks)
  })

  it('shows the landing screen with the product name', async () => {
    render(<App />)
    expect(await screen.findByText('Sit the interview before it counts.')).toBeInTheDocument()
    expect(screen.getAllByText('Callback').length).toBeGreaterThan(0)
  })

  it('starts a session and shows the first question as an interviewer turn', async () => {
    mocks.respond('/api/session', {
      session_id: 's1',
      first_question: 'Tell me about yourself.',
      question_number: 1,
      total_questions: 5,
      stage: 'intro',
      warm_up_source: 'bank',
      domain: 'ml_genai',
      audio_b64: '',
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
    expect(await screen.findByText('Tell me about yourself.')).toBeInTheDocument()
    // The label is uppercased by CSS (text-transform), not in the DOM, and the
    // test environment runs with css: false.
    expect(screen.getByText('Interviewer')).toBeInTheDocument()
  })

  it('rolls the transcript back when an answer fails, leaving no orphan turn', async () => {
    mocks.respond('/api/session', {
      session_id: 's1',
      first_question: 'Tell me about yourself.',
      question_number: 1,
      total_questions: 5,
      stage: 'intro',
      warm_up_source: 'bank',
      domain: 'ml_genai',
      audio_b64: '',
    })
    mocks.respond('/api/session/s1/answer', {}, false, 500)
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
    await screen.findByText('Tell me about yourself.')

    await userEvent.type(screen.getByPlaceholderText('Type here'), 'my answer')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument())
    expect(screen.queryByText('my answer')).not.toBeInTheDocument()
  })

  it('builds the interview around an uploaded résumé', async () => {
    await uploadResume(mocks)
    mocks.respond('/api/session', { ...START, warm_up_source: 'resume' })

    await userEvent.click(screen.getByRole('button', { name: /start interview/i }))

    await screen.findByText('Tell me about yourself.')
    const start = mocks.calls.filter((c) => c.path.endsWith('/api/session')).at(-1)
    expect(JSON.parse(start.init.body).resume_id).toBe('r1')
    // The bank-fallback notice belongs only to a résumé interview that fell back.
    expect(screen.queryByText(/uses curated questions/i)).not.toBeInTheDocument()
  })

  it('offers a general interview when the résumé cannot be used (ADR 0023)', async () => {
    await uploadResume(mocks)
    mocks.respond(
      '/api/session',
      { detail: { message: 'That résumé could not be used to tailor an interview.' } },
      false,
      409
    )

    await userEvent.click(screen.getByRole('button', { name: /start interview/i }))

    const offer = await screen.findByText(/could not be used to tailor/i)
    expect(offer).toBeInTheDocument()
    // The offer is a question, not an error banner.
    expect(screen.queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument()

    mocks.respond('/api/session', { ...START, warm_up_source: 'bank' })
    await userEvent.click(screen.getByRole('button', { name: /start the general interview/i }))

    await screen.findByText('Tell me about yourself.')
    const retry = mocks.calls.filter((c) => c.path.endsWith('/api/session')).at(-1)
    expect(JSON.parse(retry.init.body).allow_bank_fallback).toBe(true)
    expect(screen.getByText(/uses curated questions/i)).toBeInTheDocument()
  })

  it('cancelling the offer returns to the start screen with the résumé still loaded', async () => {
    await uploadResume(mocks)
    mocks.respond('/api/session', { detail: { message: 'no good' } }, false, 409)
    await userEvent.click(screen.getByRole('button', { name: /start interview/i }))
    await screen.findByText('no good')

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.getByRole('button', { name: /start interview/i })).toBeInTheDocument()
    expect(screen.getByText('cv.pdf')).toBeInTheDocument()
  })

  it('speaking an answer sends the transcription as the turn', async () => {
    await startInterview(mocks)
    mocks.respond('/api/transcribe', { transcript: 'I work on retrieval systems.' })
    mocks.respond('/api/session/s1/answer', {
      reply: 'Tell me more.',
      phase: 'probing',
      stage: 'intro',
      question_number: 1,
      total_questions: 5,
      audio_b64: '',
    })

    await userEvent.click(screen.getByRole('button', { name: 'Answer by voice' }))
    // The recorder refuses clips under a second, so this one has to be real.
    await new Promise((r) => setTimeout(r, 1100))
    await userEvent.click(screen.getByRole('button', { name: /stop/i }))

    expect(await screen.findByText('I work on retrieval systems.')).toBeInTheDocument()
    expect(await screen.findByText('Tell me more.')).toBeInTheDocument()
  })

  it('entering the coding round pins the question beside the interviewer rail', async () => {
    await startInterview(mocks)
    mocks.respond('/api/session/s1/answer', {
      reply: "Let's write some code.",
      phase: 'advancing',
      stage: 'dsa',
      question_number: 4,
      total_questions: 5,
      dsa: DSA_PAYLOAD,
      audio_b64: '',
    })

    await userEvent.type(screen.getByPlaceholderText('Type here'), 'ready')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText(DSA_PAYLOAD.prompt)).toBeInTheDocument()
    expect(screen.getByText(DSA_PAYLOAD.signature)).toBeInTheDocument()
    expect(screen.getByLabelText('editor')).toHaveValue(DSA_PAYLOAD.starter_code)
    // The rail pins the latest remark; the composer follows the candidate.
    const rail = document.querySelector('.rail')
    expect(within(rail).getByText("Let's write some code.")).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Think aloud or ask the interviewer')).toBeInTheDocument()
  })

  it('scores the interview once it reaches done', async () => {
    await startInterview(mocks)
    mocks.respond('/api/session/s1/answer', {
      reply: 'That is all — thanks for your time.',
      phase: 'done',
      stage: 'done',
      question_number: 5,
      total_questions: 5,
      audio_b64: '',
    })
    mocks.respond('/evaluation', EVALUATION)

    await userEvent.type(screen.getByPlaceholderText('Type here'), 'last answer')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('A solid interview overall.')).toBeInTheDocument()
    expect(screen.getByText('Clear structure')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start new interview/i })).toBeInTheDocument()
  })

  it('starting a new interview clears the transcript but keeps the uploaded résumé', async () => {
    await uploadResume(mocks)
    mocks.respond('/api/session', { ...START, warm_up_source: 'resume' })
    await userEvent.click(screen.getByRole('button', { name: /start interview/i }))
    await screen.findByText('Tell me about yourself.')
    mocks.respond('/api/session/s1/answer', {
      reply: 'That is all — thanks for your time.',
      phase: 'done',
      stage: 'done',
      question_number: 5,
      total_questions: 5,
      audio_b64: '',
    })
    mocks.respond('/evaluation', EVALUATION)
    await userEvent.type(screen.getByPlaceholderText('Type here'), 'last answer')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('A solid interview overall.')

    await userEvent.click(screen.getByRole('button', { name: /start new interview/i }))

    expect(screen.getByText('Sit the interview before it counts.')).toBeInTheDocument()
    expect(screen.queryByText('Tell me about yourself.')).not.toBeInTheDocument()
    expect(screen.queryByText('A solid interview overall.')).not.toBeInTheDocument()
    // Deliberate: the résumé survives, so a second interview needs no re-upload.
    expect(screen.getByText('cv.pdf')).toBeInTheDocument()
  })
})
