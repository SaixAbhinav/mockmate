import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Evaluation } from './Evaluation'
import { ScoreRow } from './ScoreRow'

const base = {
  assessment: 'A solid interview overall.',
  coverage: { answered: 2, total: 3 },
  averages: { correctness: 4, depth: 3 },
  strengths: ['Clear structure'],
  improvements: ['Give concrete numbers'],
  questions: [
    { question: 'Tell me about yourself.', correctness: 4, depth: 3, clarity: 4, comment: 'Good.' },
  ],
  dsa: null,
}

describe('ScoreRow', () => {
  it('exposes the score on a 1-5 meter', () => {
    render(<ScoreRow label="correctness" value={4} />)

    const meter = screen.getByRole('meter', { name: 'correctness' })
    expect(meter).toHaveAttribute('aria-valuenow', '4')
    expect(meter).toHaveAttribute('aria-valuemax', '5')
  })

  it('reads as a dash, not a zero, when a dimension went unscored', () => {
    render(<ScoreRow label="depth" value={null} />)

    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'depth' })).toHaveAttribute('aria-valuenow', '0')
  })
})

describe('Evaluation', () => {
  it('leads with the assessment and the coverage', () => {
    render(<Evaluation evaluation={base} />)

    expect(screen.getByText('A solid interview overall.')).toBeInTheDocument()
    expect(screen.getByText('answered 2 of 3')).toBeInTheDocument()
    expect(screen.getByText('Clear structure')).toBeInTheDocument()
    expect(screen.getByText('Give concrete numbers')).toBeInTheDocument()
  })

  it('omits empty strengths and improvements rather than showing empty headings', () => {
    render(<Evaluation evaluation={{ ...base, strengths: [], improvements: [] }} />)

    expect(screen.queryByText('Strengths')).not.toBeInTheDocument()
    expect(screen.queryByText('Work on')).not.toBeInTheDocument()
  })

  it('marks a skipped question as unanswered instead of scoring it', () => {
    render(
      <Evaluation
        evaluation={{ ...base, questions: [{ question: 'Skipped one.', skipped: true }] }}
      />
    )

    expect(screen.getByText('Not answered')).toBeInTheDocument()
    expect(screen.queryByRole('meter', { name: 'clarity' })).not.toBeInTheDocument()
  })

  it('says a question could not be scored rather than showing a zero', () => {
    render(
      <Evaluation
        evaluation={{ ...base, questions: [{ question: 'Odd one.', unscored: true }] }}
      />
    )

    expect(screen.getByText("Couldn't be scored")).toBeInTheDocument()
  })

  it('colours the coding round by whether every test passed', () => {
    const { rerender } = render(
      <Evaluation
        evaluation={{
          ...base,
          dsa: {
            averages: { code_quality: 4, approach: 3 },
            hints_used: 1,
            questions: [
              {
                question: 'Implement running_sum.',
                tests: { status: 'ok', passed: 4, total: 4 },
                code_quality: 4,
                approach: 3,
                hints: 1,
                runs: 2,
              },
            ],
          },
        }}
      />
    )

    expect(screen.getByText('Coding round')).toBeInTheDocument()
    expect(screen.getByText(/tests: 4\/4/).className).toContain('passed')
    expect(screen.getByText('hints used: 1')).toBeInTheDocument()
    expect(screen.getByText(/1 hint\(s\) · 2 test run\(s\)/)).toBeInTheDocument()

    rerender(
      <Evaluation
        evaluation={{
          ...base,
          dsa: {
            averages: {},
            hints_used: 0,
            questions: [
              { question: 'Implement running_sum.', tests: { status: 'ok', passed: 1, total: 4 } },
            ],
          },
        }}
      />
    )

    expect(screen.getByText(/tests: 1\/4/).className).toContain('failed')
  })

  it('says a coding question was never submitted', () => {
    render(
      <Evaluation
        evaluation={{
          ...base,
          dsa: {
            averages: {},
            hints_used: 0,
            questions: [{ question: 'Never got there.', skipped: true }],
          },
        }}
      />
    )

    expect(screen.getByText('Never submitted')).toBeInTheDocument()
  })

  it('omits the coding section entirely when the round never happened', () => {
    render(<Evaluation evaluation={{ ...base, dsa: { averages: {}, hints_used: 0, questions: [] } }} />)

    expect(screen.queryByText('Coding round')).not.toBeInTheDocument()
  })
})
