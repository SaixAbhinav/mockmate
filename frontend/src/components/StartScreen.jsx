import { ErrorBanner } from './ErrorBanner'
import mark from '../assets/mark.svg'

export function StartScreen({
  apiReady,
  status,
  error,
  onDismissError,
  resumeName,
  resumeStatus,
  onResumeChange,
  resumeId,
  fallbackOffer,
  onStartInterview,
  onCancelFallback,
}) {
  return (
    <main className="wrap">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="brand-name">Callback</span>
          <img className="brand-mark" src={mark} alt="" aria-hidden="true" />
          <span className="brand-tag">voice interview practice, in the open</span>
        </a>
      </header>

      <ErrorBanner error={error} onDismiss={onDismissError} />

      {/* The pitch lives on the landing page at "/" now (ADR 0033). Repeating
          the hero here would mean reading the same headline twice to start one
          interview, so this screen is only the thing it is named for. */}
      <section className="start-panel">
        <h1 className="start-title">Start your interview</h1>
        <label className="resume-drop">
          <strong>{resumeName || 'Choose a résumé'}</strong>
          <span className="hint">
            {resumeStatus === 'uploading'
              ? 'Uploading…'
              : resumeStatus === 'ready'
                ? 'Your interview will be built around this file'
                : resumeStatus === 'failed'
                  ? 'That file could not be read — try another, or skip for a general ML/GenAI interview.'
                  : 'PDF or .txt — or skip for a general ML/GenAI interview'}
          </span>
          <input type="file" accept=".pdf,.txt" onChange={onResumeChange} />
        </label>

        {fallbackOffer ? (
          <div className="fallback-offer">
            <p>{fallbackOffer.message}</p>
            <div className="dsa-actions">
              <button onClick={() => onStartInterview(true)} disabled={status === 'thinking'}>
                Start the general interview
              </button>
              <button
                className="secondary"
                onClick={onCancelFallback}
                disabled={status === 'thinking'}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => onStartInterview(false)}
            disabled={status === 'thinking' || resumeStatus === 'uploading'}
          >
            {status === 'thinking'
              ? (resumeId ? 'Reading your résumé…' : 'Starting…')
              : !apiReady
                ? 'Start interview — waking the interviewer'
                : 'Start interview'}
          </button>
        )}
        {!apiReady && (
          <p className="hint">
            The first visit can take up to a minute to wake — go ahead and pick a résumé
            meanwhile.
          </p>
        )}
      </section>
    </main>
  )
}
