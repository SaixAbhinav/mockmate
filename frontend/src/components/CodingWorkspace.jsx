import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'

export function CodingWorkspace({ dsa, code, onCodeChange, running, status, onRun, onSubmit, runReport }) {
  return (
    <div className="dsa-pane">
      <p className="dsa-signature"><code>{dsa.signature}</code></p>
      <CodeMirror
        value={code}
        height="220px"
        extensions={[python()]}
        onChange={onCodeChange}
      />
      <div className="dsa-actions">
        <button type="button" onClick={onRun} disabled={running || status === 'thinking'}>
          {running ? 'Running…' : '▶ Run tests'}
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={running || status === 'thinking'}
        >
          {status === 'thinking' ? 'Submitting…' : 'Submit'}
        </button>
      </div>
      {runReport && (
        <div className="dsa-results">
          {runReport.status === 'ok' ? (
            <p className={runReport.passed === runReport.total ? 'passed' : 'failed'}>
              {runReport.passed} of {runReport.total} test cases passed
            </p>
          ) : (
            <p className="failed">{runReport.error}</p>
          )}
          {runReport.results.filter((r) => !r.passed).map((r, i) => (
            <p key={i} className="dsa-fail">
              <code>{JSON.stringify(r.args)}</code> → expected{' '}
              <code>{JSON.stringify(r.expected)}</code>, got <code>{r.got}</code>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
