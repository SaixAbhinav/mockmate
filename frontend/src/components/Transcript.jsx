export function Transcript({ history, done, endRef, status }) {
  return (
    <div className="messages">
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
