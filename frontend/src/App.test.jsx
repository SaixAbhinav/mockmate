import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { installMocks } from './test/mocks'
import App from './App'

function baseRoutes(mocks) {
  mocks.respond('/api/voices', { voices: { v1: 'Voice One' }, default: 'v1' })
  mocks.respond('/api/health', { status: 'ok' })
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
})
