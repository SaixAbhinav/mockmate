import { render, screen } from '@testing-library/react'
import { createRef } from 'react'
import { describe, expect, it } from 'vitest'
import { Transcript } from './Transcript'

const history = [
  { role: 'assistant', content: 'First question' },
  { role: 'user', content: 'My answer' },
]

describe('Transcript', () => {
  it('labels each turn by speaker', () => {
    render(<Transcript history={history} done={false} endRef={createRef()} status="idle" />)
    expect(screen.getByText('Interviewer')).toBeInTheDocument()
    expect(screen.getByText('You')).toBeInTheDocument()
  })

  it('marks only the last turn as the wrap-up when the session is done', () => {
    const { container } = render(
      <Transcript history={history} done endRef={createRef()} status="idle" />
    )
    const turns = container.querySelectorAll('.turn')
    expect(turns[0].className).not.toContain('wrap-up')
    expect(turns[1].className).toContain('wrap-up')
  })

  it('shows a pending hint only while thinking or transcribing', () => {
    const { rerender } = render(
      <Transcript history={history} done={false} endRef={createRef()} status="idle" />
    )
    expect(screen.queryByText('thinking…')).not.toBeInTheDocument()
    rerender(<Transcript history={history} done={false} endRef={createRef()} status="thinking" />)
    expect(screen.getByText('thinking…')).toBeInTheDocument()
  })
})
