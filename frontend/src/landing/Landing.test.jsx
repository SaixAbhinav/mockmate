import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

    // Scoped to the phase list: the sample scorecard has its own "Coding round"
    // heading, the real Evaluation's.
    const phases = screen.getByRole('list', { name: /four phases/i })
    for (const phase of ['Intro', 'Warm-up', 'Coding round', 'Evaluation']) {
      expect(within(phases).getByRole('heading', { name: phase })).toBeInTheDocument()
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

  it('shows a sample scorecard, labelled as sample data', () => {
    render(<Landing />)

    const card = screen.getByRole('figure', { name: 'Example scorecard · sample data' })
    expect(within(card).getByRole('heading', { name: 'How you did' })).toBeInTheDocument()
    expect(within(card).getByText(/A strong conceptual round/)).toBeInTheDocument()
    expect(within(card).getByText('tests: 3/5')).toBeInTheDocument()
  })

  it('folds the scorecard until the visitor asks for all of it', async () => {
    render(<Landing />)

    const toggle = screen.getByRole('button', { name: 'Show the whole scorecard' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await userEvent.click(toggle)

    expect(screen.getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true')
  })
})
