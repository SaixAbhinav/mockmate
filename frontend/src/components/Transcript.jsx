// `variant` is layout only: 'full' is the centred interview column, 'rail' is
// the coding round's narrow column of earlier messages. Same turns, same
// speaker rules - the two screens share one idea rather than inventing two.
export function Transcript({ history, done, endRef, status, variant = 'full' }) {
  return (
    <div className={`messages messages--${variant}`}>
      {history.map((m, i) => (
        <div
          key={i}
          className={`turn ${m.role}${done && i === history.length - 1 ? ' wrap-up' : ''}`}
        >
          <span className="turn-label">{m.role === 'user' ? 'You' : 'Interviewer'}</span>
          <p className="turn-text">{m.content}</p>
        </div>
      ))}
      {(status === 'thinking' || status === 'transcribing') && (
        <p className="hint">{status}…</p>
      )}
      <div ref={endRef} />
    </div>
  )
}
