export function ErrorBanner({ error, onDismiss }) {
  if (!error) return null
  return (
    <div className="banner">
      <span>{error}</span>
      <button type="button" onClick={onDismiss} aria-label="Dismiss">
        ✕
      </button>
    </div>
  )
}
