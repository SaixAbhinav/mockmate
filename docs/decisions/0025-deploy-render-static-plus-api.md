# ADR 0025: Deploy on Render as a static SPA plus a single API container

Date: 2026-07-24 · Amended: 2026-07-25 · Status: proposed

## Context

MockMate has only ever run locally — the README documents `uvicorn` and `npm
run dev` on a developer's machine. The goal now is a **personal / portfolio
deployment**: a live URL to show a handful of people, not a public product open
to the internet at large. That exposure level is the load-bearing assumption of
this ADR; a fully public deployment would change several answers below.

Four facts shape the decision, each checked against the code or the host's docs
rather than assumed:

- **The frontend already calls the API by relative path.** Every request in
  `frontend/src/App.jsx` is `fetch('/api/...')` — there is no hard-coded backend
  host. Whatever we deploy must preserve **one apparent origin**, or those paths
  break and CORS comes back.
- **Session state is in-memory** ([ADR 0007](0007-session-state-in-memory.md)) —
  a module-level dict in `main.py`. The backend is a **single long-lived
  process**: it cannot be horizontally scaled, and a restart or redeploy drops
  every active interview. [ADR 0021](0021-session-store-interface.md) built the
  `SessionStore` seam that would let this swap to persistence; it is not wired.
- **The runner executes untrusted candidate Python in a soft sandbox.**
  `runner.py` states plainly that its subprocess isolation is "a guardrail, not a
  hard boundary — no network blocking, no memory caps… container isolation is a
  later hardening day."
- **Free hosting now costs a credit card almost everywhere.** Fly.io (this ADR's
  original choice) requires a card even for its trial allowance; Hugging Face
  Docker Spaces became PRO-only; Koyeb closed its free entry tier to new users.
  **Render still offers free web services with no payment details**, which is why
  the host changed between this ADR's first draft and this amendment.

The in-memory sessions and the subprocess runner together also rule out a
serverless host: stateless invocations do not preserve the session dict, and the
runner fights serverless execution limits. MockMate's backend is a **server, not
a set of functions**.

Render's free web services carry one sharp constraint: they **spin down after 15
minutes of inactivity, with a 30–60 second cold start**. For a demo, a visitor
staring at a blank minute is the single worst failure mode — worse than any
resource limit.

## Decision

**Deploy as two Render services behind one apparent origin: a static SPA and a
single API container.**

- **A Render Static Site** serves the built React app. It is free, always-on and
  CDN-backed, so **the page itself always loads instantly** — the cold start can
  never blank the first impression.
- **A Render Web Service** runs the backend from a `Dockerfile` (uvicorn,
  non-root, `$PORT`). This is the only service that sleeps.
- **A rewrite rule maps `/api/*` to the backend service.** Render's docs confirm
  a rewrite destination "can be either a path or a full, publicly accessible
  URL." Because a *rewrite* resolves server-side (unlike a redirect), the browser
  still sees a single origin: the existing relative `/api` paths keep working
  unchanged and **production needs no CORS**.
- **The start screen doubles as a landing page, and wakes the backend on
  mount.** It carries what the project is, how a Session runs, and links to these
  ADRs — and it fires `GET /api/health` (`main.py:365`) as soon as it renders.
  The backend therefore boots *while the visitor reads*, and the natural flow
  that follows — read, then upload a résumé, then start — spends far more human
  time than the 30–60s cold start needs. **The landing content is the mitigation,
  not decoration; the health ping is what makes it work.** Without that ping the
  cold start would simply move to the "Start interview" click.
- **Single backend instance** (ADR 0007). A redeploy or crash interrupts any live
  interview; that is accepted for a demo and is the explicit trigger to wire ADR
  0021's store if it stops being acceptable.
- **The runner timeout becomes env-configurable.** `run_tests()` already takes
  `timeout_seconds` (`runner.py:103`); Render's free tier is CPU-throttled, so a
  hard-coded 5s risks **false timeouts on correct answers** in the coding round.
  Production raises it via env rather than by editing the default.
- **Secrets** (`GROQ_API_KEY`, optional Gemini key) live in Render's secret
  store, never in the image or git. `PORT`, CORS origins and the runner timeout
  are read from the environment.
- **Runner residual risk is accepted and named, not solved.** At demo exposure
  the realistic threat is "a stranger who finds the URL submits Python that makes
  outbound calls or burns CPU." Container-level limits bound the blast radius; we
  do **not** build real isolation (egress firewall, per-run ephemeral containers,
  gVisor, an offloaded sandbox). Keep the URL unlisted rather than indexed. If
  exposure widens to genuinely public, that isolation becomes its own hardening
  ADR — the "later hardening day" `runner.py` names.

## Consequences

- **The cold start stops being a first-impression problem.** The page is always
  instant; the wake happens behind reading time. The residual case is a visitor
  who lands and immediately clicks Start, who still waits.
- **Two services instead of one.** More moving parts than a single container:
  two dashboards, two deploys, and the rewrite rule is a config dependency — if
  the backend's URL changes, the static site's rewrite must change with it.
- **Frontend and backend can now drift in version.** They release separately, so
  a frontend expecting a new API shape can ship ahead of it. Previously (as one
  image) they were coupled by construction. At this size it is a discipline
  problem, not an architectural one.
- **No horizontal scale; redeploys drop live sessions** (ADR 0007). Bounded and
  acceptable at demo scale; the fix is designed but unbuilt (ADR 0021).
- **The 512 MB / throttled-CPU envelope is unverified.** `langgraph` and
  `langchain-core` are heavy imports and each runner subprocess adds more. The
  footprint should be **measured against the real image before deploying**, not
  assumed to fit.
- **The accepted runner risk is a real, bounded liability**, written down so the
  trade-off stays visible rather than implicit.
- **The README's "self-hostable" claim becomes real** — a `Dockerfile` anyone can
  build, plus a documented deploy path.
- **No new runtime dependency and no provider change.** edge-tts still calls
  Microsoft's endpoint server-side; Groq/Gemini keys stay server-side.

## Alternatives considered

- **Strict single-origin: one container serving both the SPA and the API.** This
  ADR's original decision, and simpler — one service, no rewrite, no version
  drift. Rejected because the cold start would then blank **the whole page**, not
  just the first API call. Trading one service for an always-instant landing page
  is worth it precisely because this is a portfolio demo, where the first
  impression is the product.
- **Fly.io** (originally chosen here). Rejected: requires a credit card even for
  the free allowance. The architecture is unchanged if it is ever revisited —
  only the host manifest differs.
- **Hugging Face Docker Spaces / Koyeb.** Rejected on current pricing: Docker
  Spaces now need PRO, and Koyeb's free entry tier is closed to new users.
- **Serverless for the whole app (Vercel / Cloud Run / Lambda).** Rejected on the
  code: ADR 0007's in-memory sessions do not survive stateless invocations, and
  the runner's subprocess execution fights serverless limits. Vercel remains a
  fine host for the *static half*, but Render's static site keeps everything on
  one platform with one rewrite.
- **Keep-alive pinging to prevent spin-down.** Rejected: it works against the
  free tier's intent, and the landing-page warm-up achieves the same result
  honestly, only when someone is actually visiting.
- **A login page on the landing screen.** Rejected: MockMate has no accounts —
  ADR 0009 deferred them and Sessions are anonymous (ADR 0007) — so a login
  screen would be a facade with nothing behind it. Project and architecture
  content stalls just as well and is honest.
- **Full runner isolation now** (per-run containers, gVisor, Judge0/Piston).
  Deferred — disproportionate for a portfolio demo. Becomes its own ADR if the
  audience widens.

## Status

Proposed. Two points are worth a second opinion before this is accepted: the
accepted runner residual risk (defensible at demo exposure, but a genuine
decision), and the two-service split, which buys an always-instant page at the
cost of version coupling that a single image gave for free.
