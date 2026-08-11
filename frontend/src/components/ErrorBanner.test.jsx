import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ErrorBanner } from './ErrorBanner'

describe('ErrorBanner', () => {
  it('renders nothing when there is no error', () => {
    const { container } = render(<ErrorBanner error={null} onDismiss={vi.fn()} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('shows the message with a dismiss control', async () => {
    const onDismiss = vi.fn()
    render(<ErrorBanner error="Microphone permission denied" onDismiss={onDismiss} />)

    expect(screen.getByText('Microphone permission denied')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))

    expect(onDismiss).toHaveBeenCalled()
  })
})
