import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { InterviewerRail } from './InterviewerRail'

const history = [
  { role: 'assistant', content: 'First question' },
  { role: 'user', content: 'My answer' },
  { role: 'assistant', content: 'How would you handle an empty list?' },
]

describe('InterviewerRail', () => {
  it('pins the latest interviewer remark and folds the rest away', () => {
    render(<InterviewerRail history={history} status="idle" />)

    expect(screen.getByText('How would you handle an empty list?')).toBeInTheDocument()
    expect(screen.getByText('2 earlier messages')).toBeInTheDocument()
    // Folded, but present - the record is one click deep, not discarded.
    expect(screen.getByText('First question')).toBeInTheDocument()
    expect(screen.getByText('My answer')).toBeInTheDocument()
  })

  it('shows no disclosure when the latest remark is the whole conversation', () => {
    render(<InterviewerRail history={[history[0]]} status="idle" />)

    expect(screen.queryByText(/earlier message/)).not.toBeInTheDocument()
  })

  it('renders without a remark before the interviewer has spoken', () => {
    render(<InterviewerRail history={[]} status="idle" />)

    expect(screen.getByText('Interviewer')).toBeInTheDocument()
  })

  it('shows a pending hint while thinking', () => {
    render(<InterviewerRail history={history} status="thinking" />)

    expect(screen.getByText('thinking…')).toBeInTheDocument()
  })
})
