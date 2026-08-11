export function Composer({
  value,
  onDraftChange,
  onSubmit,
  status,
  placeholder,
  onStartRecording,
  onStopRecording,
}) {
  return (
    <form onSubmit={onSubmit} className="composer">
      <input
        value={value}
        onChange={(e) => onDraftChange(e.target.value)}
        placeholder={placeholder}
        disabled={status === 'thinking'}
      />
      <button type="submit" disabled={status === 'thinking' || !value.trim()}>
        Send
      </button>
      {status === 'recording' ? (
        <button type="button" className="recording" onClick={onStopRecording}>
          ⏹ Stop
        </button>
      ) : (
        <button
          type="button"
          onClick={onStartRecording}
          disabled={status !== 'idle'}
          aria-label="Answer by voice"
        >
          🎤
        </button>
      )}
    </form>
  )
}
