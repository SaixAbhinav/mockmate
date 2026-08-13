import { useEffect, useRef, useState } from 'react'
import { useApiReady } from '../hooks/useApiReady'
import heroArt from '../assets/hero-art.png'
import mark from '../assets/mark.svg'
import './landing.css'

const APP_URL = '/app.html'
const REPO_URL = 'https://github.com/SaixAbhinav/mockmate'
const DECISIONS_URL = 'https://github.com/SaixAbhinav/mockmate/tree/main/docs/decisions'

// One label per intent (there is exactly one "start" intent on this page, and
// it reads the same in the nav, the hero and the closing section).
const START_LABEL = 'Start practising'

// Reveals a section once it enters the viewport. IntersectionObserver rather
// than a scroll listener: no work on frames where nothing crosses a boundary.
// Under prefers-reduced-motion the element starts visible and the observer is
// never created, so there is no transition to sit through.
function useReveal() {
  const ref = useRef(null)
  const [shown, setShown] = useState(() =>
    typeof window === 'undefined'
      ? true
      : window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    if (shown || !ref.current) return
    if (typeof IntersectionObserver === 'undefined') {
      setShown(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true)
          observer.disconnect()
        }
      },
      { threshold: 0.15 },
    )
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [shown])

  return [ref, shown]
}

function Reveal({ as: Tag = 'section', className = '', children, ...rest }) {
  const [ref, shown] = useReveal()
  return (
    <Tag ref={ref} className={`reveal ${shown ? 'is-shown' : ''} ${className}`.trim()} {...rest}>
      {children}
    </Tag>
  )
}

// The phases a Session actually runs through (ADR 0012). Named by phase, not
// numbered: the names are the domain vocabulary the rest of the app uses.
const PHASES = [
  {
    name: 'Intro',
    body: 'It opens the way a real one does. Tell me about yourself, and it listens to the answer rather than reading from a script.',
  },
  {
    name: 'Warm-up',
    body: 'Questions built from your résumé, so you are defending your own work. Skip the upload and you get a general ML and GenAI round instead.',
  },
  {
    name: 'Coding round',
    body: 'Two Python questions run against real test cases in a sandboxed subprocess. The interviewer watches you type, checks in when you stall, and offers a hint when the tests keep failing.',
  },
  {
    name: 'Evaluation',
    body: 'A scored write-up covering both halves: rubric scores for the spoken rounds, measured test results for the code, and any hints you used reported honestly.',
  },
]

const QUALITIES = [
  {
    title: 'It read your résumé',
    body: 'Upload a PDF and the warm-up is grounded in what is actually on it. The interview field is derived from your own experience, not picked from a menu.',
    size: 'wide',
  },
  {
    title: 'It watches you code',
    body: 'Check-ins are anchored to your typing, with cooldowns so it never nags. Two silent minutes earns an invitation to think out loud, not an interruption.',
    size: 'tall',
  },
  {
    title: 'The tests are real',
    body: 'Your code runs. Passing and failing cases are measured, never guessed at by a model.',
    size: 'narrow',
  },
  {
    title: 'You can talk while you type',
    body: 'Voice stays live through the coding round, so you can reason out loud the way you would across a desk.',
    size: 'narrow',
  },
]

export function Landing() {
  const apiReady = useApiReady()

  return (
    <div className="landing-page">
      <header className="lp-nav">
        <a className="lp-brand" href="/">
          <img src={mark} alt="" aria-hidden="true" width="20" height="20" />
          <span>Callback</span>
        </a>
        <nav className="lp-nav-links">
          <a href={REPO_URL} target="_blank" rel="noreferrer">
            Source
          </a>
          <a className="lp-cta lp-cta-small" href={APP_URL}>
            {START_LABEL}
          </a>
        </nav>
      </header>

      <main>
        <section className="lp-hero">
          <div className="lp-hero-copy">
            <p className="lp-eyebrow">Open source, self-hostable</p>
            <h1>Sit the interview before it counts.</h1>
            <p className="lp-lede">
              Upload a résumé. Callback builds an interview around it, then scores you the
              way a real panel would.
            </p>
            <div className="lp-actions">
              <a className="lp-cta" href={APP_URL}>
                {START_LABEL}
              </a>
              <a className="lp-link" href="#architecture">
                How it is built
              </a>
            </div>
          </div>
          <img className="lp-hero-art" src={heroArt} alt="" aria-hidden="true" />
        </section>

        <Reveal className="lp-phases" aria-labelledby="phases-heading">
          <h2 id="phases-heading">A Session runs in four phases.</h2>
          <ol className="lp-phase-list">
            {PHASES.map((phase) => (
              <li key={phase.name}>
                <h3>{phase.name}</h3>
                <p>{phase.body}</p>
              </li>
            ))}
          </ol>
        </Reveal>

        <Reveal className="lp-qualities" aria-labelledby="qualities-heading">
          <h2 id="qualities-heading">Closer to the real thing than a question list.</h2>
          <div className="lp-grid">
            {QUALITIES.map((quality) => (
              <article key={quality.title} className={`lp-tile lp-tile-${quality.size}`}>
                <h3>{quality.title}</h3>
                <p>{quality.body}</p>
              </article>
            ))}
          </div>
        </Reveal>

        <Reveal className="lp-architecture" id="architecture" aria-labelledby="arch-heading">
          <div className="lp-arch-copy">
            <h2 id="arch-heading">Built in the open, decisions and all.</h2>
            <p>
              Every significant choice is written down as a numbered decision record before
              the code lands, including the ones that were reversed later. The
              infrastructure is defined in Terraform and deployed by a pipeline that holds
              no AWS keys.
            </p>
            <p className="lp-arch-links">
              <a href={DECISIONS_URL} target="_blank" rel="noreferrer">
                Read the decision records
              </a>
            </p>
          </div>
          <dl className="lp-spec">
            <div>
              <dt>Runtime</dt>
              <dd>FastAPI on Lambda, behind an API Gateway HTTP API and CloudFront.</dd>
            </div>
            <div>
              <dt>State</dt>
              <dd>
                DynamoDB, with a conditional write so a Session is scored exactly once even
                when requests fan out.
              </dd>
            </div>
            <div>
              <dt>Delivery</dt>
              <dd>
                Terraform for every resource, applied by GitHub Actions over OIDC. No
                long-lived credentials.
              </dd>
            </div>
          </dl>
        </Reveal>

        <Reveal className="lp-close" aria-labelledby="close-heading">
          <h2 id="close-heading">Take one now.</h2>
          <p>
            No account, and no API key needed to try it. Without one you get a scripted
            interviewer that walks the questions; add a free Groq or Gemini key and it
            probes your answers properly.
          </p>
          <a className="lp-cta" href={APP_URL}>
            {START_LABEL}
          </a>
          {!apiReady && (
            <p className="lp-note">
              The interviewer wakes on the first visit, which can take a moment.
            </p>
          )}
        </Reveal>
      </main>

      <footer className="lp-footer">
        <span>Callback</span>
        <a href={REPO_URL} target="_blank" rel="noreferrer">
          GitHub
        </a>
      </footer>
    </div>
  )
}
