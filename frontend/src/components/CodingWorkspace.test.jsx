import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CodingWorkspace } from './CodingWorkspace'

// CodeMirror needs layout APIs jsdom does not have, and none of these
// assertions are about the editor itself.
vi.mock('@uiw/react-codemirror', () => ({
  default: ({ value }) => <textarea readOnly value={value} aria-label="editor" />,
}))

const dsa = {
  prompt: 'Implement running_sum: return the running total at each index.',
  signature: 'def running_sum(nums: list[int]) -> list[int]:',
  starter_code: 'def running_sum(nums):\n    pass\n',
}

function renderWorkspace(props = {}) {
  return render(
    <CodingWorkspace
      dsa={dsa}
      code={dsa.starter_code}
      onCodeChange={() => {}}
      running={false}
      status="idle"
      onRun={() => {}}
      onSubmit={() => {}}
      runReport={null}
      {...props}
    />
  )
}

describe('CodingWorkspace', () => {
  it('pins the question and the signature above the editor', () => {
    renderWorkspace()

    expect(screen.getByText(dsa.prompt)).toBeInTheDocument()
    expect(screen.getByText(dsa.signature)).toBeInTheDocument()
  })

  it('summarises a passing run without a failure table', () => {
    renderWorkspace({
      runReport: {
        status: 'ok',
        passed: 3,
        total: 3,
        results: [{ args: [1], expected: 1, got: '1', passed: true }],
      },
    })

    expect(screen.getByText('3 of 3 passed').className).toContain('passed')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('tabulates the failing cases as args, expected and got', () => {
    renderWorkspace({
      runReport: {
        status: 'ok',
        passed: 1,
        total: 2,
        results: [
          { args: [[1, 2]], expected: [1, 3], got: '[1, 2]', passed: false },
          { args: [[]], expected: [], got: '[]', passed: true },
        ],
      },
    })

    expect(screen.getByText('1 of 2 passed').className).toContain('failed')
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(rows).toHaveLength(2) // header plus the one failure
    const cells = within(rows[1]).getAllByRole('cell')
    expect(cells.map((c) => c.textContent)).toEqual(['[[1,2]]', '[1,3]', '[1, 2]'])
  })

  it('reports a runner error instead of a summary', () => {
    renderWorkspace({
      runReport: { status: 'error', error: 'SyntaxError: bad', passed: 0, total: 0, results: [] },
    })

    expect(screen.getByText('SyntaxError: bad')).toBeInTheDocument()
  })

  it('disables both actions while a run is in flight', () => {
    renderWorkspace({ running: true })

    expect(screen.getByRole('button', { name: 'Running…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Submit' })).toBeDisabled()
  })
})
