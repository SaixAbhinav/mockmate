import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'

export function CodingWorkspace({ dsa, code, onCodeChange, running, status, onRun, onSubmit, runReport }) {
  const failures = runReport?.results?.filter((r) => !r.passed) ?? []

  return (
    <div className="dsa-pane">
      {/* Pinned, so the question is readable while you write the answer to it.
          It stays in the transcript too - it is a real spoken turn. */}
      <p className="dsa-prompt">{dsa.prompt}</p>
      <p className="dsa-signature"><code>{dsa.signature}</code></p>
      <CodeMirror
        value={code}
        height="100%"
        theme="dark"
        className="dsa-editor"
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
              {runReport.passed} of {runReport.total} passed
            </p>
          ) : (
            <p className="failed">{runReport.error}</p>
          )}
          {/* A table, not a sentence: three values jammed into prose is
              unreadable at the glance this is meant to be read at. */}
          {failures.length > 0 && (
            <table className="dsa-fails">
              <thead>
                <tr>
                  <th scope="col">Args</th>
                  <th scope="col">Expected</th>
                  <th scope="col">Got</th>
                </tr>
              </thead>
              <tbody>
                {failures.map((r, i) => (
                  <tr key={i}>
                    <td><code>{JSON.stringify(r.args)}</code></td>
                    <td><code>{JSON.stringify(r.expected)}</code></td>
                    <td><code>{r.got}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
