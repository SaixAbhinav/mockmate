// Scores are 1-5; a bar reads faster than a number in a pill.
export function ScoreRow({ label, value }) {
  return (
    <div className="score-row">
      <span>{label}</span>
      <span
        className="score-bar"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={5}
        aria-valuenow={value ?? 0}
        aria-label={label}
      >
        <span style={{ width: `${((value ?? 0) / 5) * 100}%` }} />
      </span>
      <span>{value ?? '—'}</span>
    </div>
  )
}
