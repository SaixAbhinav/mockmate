import { ErrorBanner } from './ErrorBanner'
import heroArt from '../assets/hero-art.png'
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
        <div className="brand">
          <span className="brand-name">Callback</span>
          <img className="brand-mark" src={mark} alt="" aria-hidden="true" />
          <span className="brand-tag">voice interview practice, in the open</span>
        </div>
      </header>

      <ErrorBanner error={error} onDismiss={onDismissError} />

      <div className="landing">
        <section className="hero">
          <img className="hero-art" src={heroArt} alt="" aria-hidden="true" />
          <div className="hero-body">
            <p className="kicker">Open source · self-hostable</p>
            <h1>Sit the interview before it counts.</h1>
            <p className="lede">
              Upload a résumé and Callback builds an interview around it — an intro, a
              résumé-grounded warm-up, then two sandboxed Python questions with an
              interviewer watching as you type. You leave with a scored evaluation.
            </p>
          </div>
        </section>

        <ol className="landing-steps">
          <li>Upload a résumé — optional, skip it for a general ML/GenAI interview</li>
          <li>Answer out loud; the interviewer probes what you say</li>
          <li>Solve two coding questions, then read your scored evaluation</li>
        </ol>

        <p className="hint">
          Built in the open —{' '}
          <a href="https://github.com/SaixAbhinav/mockmate" target="_blank" rel="noreferrer">
            source and architecture decisions on GitHub
          </a>
          .
        </p>
      </div>

      <section className="start-panel">
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
