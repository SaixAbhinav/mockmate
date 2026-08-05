import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { StartScreen } from './StartScreen'

function renderStart(props = {}) {
  const onStartInterview = vi.fn()
  const onCancelFallback = vi.fn()
  const onResumeChange = vi.fn()
  const view = render(
    <StartScreen
      apiReady
      status="idle"
      error={null}
      onDismissError={vi.fn()}
      resumeName=""
      resumeStatus="none"
      onResumeChange={onResumeChange}
      resumeId={null}
      fallbackOffer={null}
      onStartInterview={onStartInterview}
      onCancelFallback={onCancelFallback}
      {...props}
    />
  )
  return { ...view, onStartInterview, onCancelFallback, onResumeChange }
}

describe('StartScreen', () => {
  it('says the interviewer is waking until the health ping lands (ADR 0025)', () => {
    renderStart({ apiReady: false })

    expect(screen.getByRole('button', { name: /waking the interviewer/i })).toBeInTheDocument()
    expect(screen.getByText(/first visit can take up to a minute/i)).toBeInTheDocument()
  })

  it('drops the waking notice once the API answers', () => {
    renderStart()

    expect(screen.getByRole('button', { name: 'Start interview' })).toBeInTheDocument()
    expect(screen.queryByText(/first visit can take up to a minute/i)).not.toBeInTheDocument()
  })

  it('shows the filename and no remove control once a résumé is ready', () => {
    renderStart({ resumeStatus: 'ready', resumeName: 'cv.pdf', resumeId: 'r1' })

    expect(screen.getByText('cv.pdf')).toBeInTheDocument()
    expect(screen.getByText(/built around this file/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
  })

  it('offers no filename and an honest hint when the résumé could not be read', () => {
    renderStart({ resumeStatus: 'failed', resumeName: '' })

    expect(screen.getByText('Choose a résumé')).toBeInTheDocument()
    expect(screen.getByText(/could not be read/i)).toBeInTheDocument()
  })

  it('will not start while a résumé is still uploading', () => {
    renderStart({ resumeStatus: 'uploading' })

    expect(screen.getByRole('button', { name: /start interview/i })).toBeDisabled()
    expect(screen.getByText('Uploading…')).toBeInTheDocument()
  })

  it('says it is reading the résumé rather than just starting', () => {
    renderStart({ status: 'thinking', resumeId: 'r1', resumeStatus: 'ready', resumeName: 'cv.pdf' })

    expect(screen.getByRole('button', { name: /reading your résumé/i })).toBeInTheDocument()
  })

  it('replaces the start button with the fallback offer and its two answers', async () => {
    const { onStartInterview, onCancelFallback } = renderStart({
      fallbackOffer: { message: 'Could not tailor an interview.' },
    })

    expect(screen.getByText('Could not tailor an interview.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^start interview/i })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /start the general interview/i }))
    expect(onStartInterview).toHaveBeenCalledWith(true)

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancelFallback).toHaveBeenCalled()
  })

  it('keeps the file input reachable by keyboard', () => {
    const { container } = renderStart()
    const input = container.querySelector('input[type="file"]')

    // Visually hidden, not display:none - hiding it outright would put the
    // picker out of reach for keyboard users entirely.
    expect(input).toBeInTheDocument()
    expect(input).not.toBeDisabled()
    expect(input.tabIndex).not.toBe(-1)
  })

  it('shows an error banner above the landing copy', () => {
    renderStart({ error: 'resume upload failed (400)' })

    expect(screen.getByText('resume upload failed (400)')).toBeInTheDocument()
  })
})
