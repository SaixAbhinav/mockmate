import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Landing } from './Landing'

// jsdom has no IntersectionObserver, and the reveal hook falls back to showing
// content immediately when it is missing. That fallback is what these tests
// exercise, and it is also what a browser without the API would get.
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true })),
  )
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Landing', () => {
  it('sends every start action to the interview page (ADR 0033)', () => {
    render(<Landing />)

    const startLinks = screen.getAllByRole('link', { name: 'Start practising' })
    expect(startLinks.length).toBeGreaterThan(1)
    for (const link of startLinks) {
      expect(link).toHaveAttribute('href', '/app.html')
    }
  })

  it('names the four phases a Session runs through (ADR 0012)', () => {
    render(<Landing />)

    for (const phase of ['Intro', 'Warm-up', 'Coding round', 'Evaluation']) {
      expect(screen.getByRole('heading', { name: phase })).toBeInTheDocument()
    }
  })

  it('pings the API on mount so the Lambda wakes while the page is read (ADR 0029)', () => {
    render(<Landing />)

    expect(fetch).toHaveBeenCalledWith('/api/health')
  })

  it('drops the waking notice once the API answers', async () => {
    render(<Landing />)

    expect(screen.getByText(/interviewer wakes on the first visit/i)).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByText(/interviewer wakes on the first visit/i)).not.toBeInTheDocument(),
    )
  })

  it('spends no state colour on decoration (ADR 0030)', () => {
    const { container } = render(<Landing />)

    // --pass/--fail/--pending mean "a test passed/failed" and nothing else.
    // An inline style reaching for one here would be the regression.
    const styled = container.querySelectorAll('[style]')
    for (const node of styled) {
      expect(node.getAttribute('style')).not.toMatch(/--(pass|fail|pending)/)
    }
  })
})
