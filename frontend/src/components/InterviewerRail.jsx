import { Transcript } from './Transcript'

// The coding round's right-hand column. The candidate is looking at the editor,
// so the rail pins only the interviewer's latest remark and folds the rest of
// the conversation away - the full record is still one disclosure click deep.
export function InterviewerRail({ history, status }) {
  const latestIndex = history.map((m) => m.role).lastIndexOf('assistant')
  const latest = latestIndex === -1 ? null : history[latestIndex]
  const earlier = latestIndex === -1 ? history : history.slice(0, latestIndex)

  return (
    <aside className="rail">
      <span className="turn-label">Interviewer</span>
      {latest && <p className="rail-latest">{latest.content}</p>}
      {(status === 'thinking' || status === 'transcribing') && (
        <p className="hint">{status}…</p>
      )}
      {earlier.length > 0 && (
        <details className="rail-earlier">
          <summary>
            {earlier.length} earlier {earlier.length === 1 ? 'message' : 'messages'}
          </summary>
          <Transcript history={earlier} done={false} status="idle" variant="rail" />
        </details>
      )}
    </aside>
  )
}
