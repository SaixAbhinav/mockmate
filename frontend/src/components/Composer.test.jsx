import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from './Composer'

function renderComposer(props = {}) {
  const onSubmit = vi.fn((e) => e.preventDefault())
  const onDraftChange = vi.fn()
  const onStartRecording = vi.fn()
  const onStopRecording = vi.fn()
  render(
    <Composer
      value=""
      onDraftChange={onDraftChange}
      onSubmit={onSubmit}
      status="idle"
      placeholder="Type here"
      onStartRecording={onStartRecording}
      onStopRecording={onStopRecording}
      {...props}
    />
  )
  return { onSubmit, onDraftChange, onStartRecording, onStopRecording }
}

describe('Composer', () => {
  it('cannot send an empty or whitespace-only draft', () => {
    renderComposer({ value: '   ' })

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('sends a real draft', async () => {
    const { onSubmit } = renderComposer({ value: 'my answer' })

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(onSubmit).toHaveBeenCalled()
  })

  it('reports each keystroke to the owner', async () => {
    const { onDraftChange } = renderComposer()

    await userEvent.type(screen.getByPlaceholderText('Type here'), 'hi')

    expect(onDraftChange).toHaveBeenCalledWith('h')
  })

  it('locks the input while the interviewer is thinking', () => {
    renderComposer({ value: 'my answer', status: 'thinking' })

    expect(screen.getByPlaceholderText('Type here')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('offers the microphone when idle and the stop button while recording', async () => {
    const { onStartRecording } = renderComposer()
    await userEvent.click(screen.getByRole('button', { name: 'Answer by voice' }))
    expect(onStartRecording).toHaveBeenCalled()

    const { onStopRecording } = renderComposer({ status: 'recording' })
    await userEvent.click(screen.getAllByRole('button', { name: /stop/i })[0])
    expect(onStopRecording).toHaveBeenCalled()
  })

  it('does not offer the microphone mid-turn', () => {
    renderComposer({ status: 'speaking' })

    expect(screen.getByRole('button', { name: 'Answer by voice' })).toBeDisabled()
  })
})
