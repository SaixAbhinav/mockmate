# ADR 0025: Deploy as a single-origin container on Fly.io, one instance

Date: 2026-07-24 · Status: proposed

## Context

MockMate has only ever run locally — the README documents `uvicorn` and `npm
run dev` on a developer's machine. The goal now is a **personal / portfolio
deployment**: a live URL to show a handful of people, not a public product open
to the internet at large. That exposure level is the load-bearing assumption of
this ADR; a fully public deployment would change several answers below.

Three facts about the codebase shape the decision, each checked against the code
rather than assumed:

- **The frontend already calls the API by relative path.** Every request in
  `frontend/src/App.jsx` is `fetch('/api/...')` — there is no hard-coded backend
  host. Serving the built SPA and the API from **one origin** is therefore the
  natural shape: no CORS in production, no cross-host proxy.
- **Session state is in-memory** ([ADR 0007](0007-session-state-in-memory.md)) —
  a module-level dict in `main.py`. The app is a **single long-lived process**:
  it cannot be horizontally scaled, and a restart or redeploy drops every active
  interview. [ADR 0021](0021-session-store-interface.md) built the `SessionStore`
  seam that would let this swap to persistence, but that is not wired.
- **The runner executes untrusted candidate Python in a soft sandbox.**
  `runner.py` states plainly that its subprocess isolation is "a guardrail, not a
  hard boundary — no network blocking, no memory caps… container isolation is a
  later hardening day." Deploying to a public URL is, in principle, that day.

The second and third facts also rule out a serverless host: ADR 0007's in-memory
sessions do not survive stateless, ephemeral function invocations, and the runner
spawns subprocesses under execution-time limits that serverless platforms impose.
MockMate's backend is a **server, not a set of functions.**

## Decision

**Deploy as a single Docker image, single origin, single instance, on Fly.io.**

- **Single origin.** The FastAPI process serves the built React SPA (static
  files with SPA fallback) *and* the `/api/*` routes behind one URL. No
  production CORS, no split-host proxy. The `allow_origins` hard-coded to
  `localhost:5173` becomes env-driven, defaulting to the dev origin.
- **Single image.** A multi-stage `Dockerfile`: stage one builds the frontend
  (`npm ci && npm run build`); stage two installs backend dependencies with uv,
  copies the built assets, and runs uvicorn as a **non-root** user on `$PORT`.
- **Single instance** (ADR 0007). We accept that a redeploy or crash interrupts
  any live interview. This is acceptable for a demo and is the explicit trigger
  to wire ADR 0021's store if it ever stops being acceptable.
- **Fly.io**, because the runner needs a **real, resource-limited container** —
  not a serverless box. Fly gives a per-machine memory/CPU cap (set in
  `fly.toml`), a usable free allowance, and fits the "open, self-hostable" ethos.
- **Secrets** (`GROQ_API_KEY`, optional `GEMINI_API_KEY`) live in Fly secrets,
  never in the image or git. `PORT` and CORS origins are read from the
  environment.
- **Runner residual risk is accepted and named, not solved.** At demo exposure,
  the realistic threat is "a stranger who finds the URL submits Python that makes
  outbound network calls or burns resources." We reduce blast radius with
  container-level limits (non-root, a memory cap, Fly's per-machine caps) but do
  **not** build real isolation (egress firewall, per-run ephemeral containers,
  gVisor, or an offloaded sandbox service). If exposure ever widens to fully
  public, that isolation becomes its own hardening ADR — the "later hardening
  day" `runner.py` names.

## Consequences

- **The README's "self-hostable" claim becomes real and reproducible** — a
  `Dockerfile` anyone can build, plus a documented `fly deploy` path.
- **No horizontal scale, and redeploys drop live sessions** (ADR 0007). Bounded
  and acceptable at demo scale; the fix is already designed (ADR 0021), just not
  built.
- **Frontend and backend release as one artifact.** This removes CORS and
  config drift but couples their versions — fine at this size, and it is what the
  relative `/api` paths already assume.
- **The accepted runner risk is a real, bounded liability**, not an oversight.
  Container limits shrink the blast radius; they do not isolate egress on the
  free tier. This is written down so the trade-off is visible, not implicit.
- **The build gains a Node stage and a Docker image.** Multi-stage keeps the
  runtime image slim (build tooling stays in stage one). CI (the pytest/lint
  workflow) is unchanged; a container build can be added later if desired.
- **No new runtime dependency and no provider change.** edge-tts still calls
  Microsoft's endpoint server-side; Groq/Gemini keys stay server-side.

## Alternatives considered

- **Split: frontend on Vercel, backend on Fly.** Vercel is excellent for the
  static SPA, but the relative `/api` paths would need Vercel rewrites (or an
  absolute backend URL plus re-enabled CORS), and it means two dashboards and two
  deploys. Rejected for demo simplicity — one origin is less to manage. (Vercel
  cannot host the backend at all; see below.)
- **Serverless for the whole app (Vercel / Lambda).** Rejected on the code:
  ADR 0007's in-memory sessions do not survive stateless invocations, and the
  runner's subprocess execution is hostile to serverless time limits and process
  constraints.
- **Full runner isolation now** (per-run containers, gVisor, or an offloaded
  sandbox like Judge0/Piston). Deferred — disproportionate for a portfolio demo.
  Becomes its own ADR if the audience widens.
- **Render / Railway instead of Fly.** Equivalent container hosts; the same
  `Dockerfile` works on any of them. Fly chosen for real containers, per-machine
  resource caps, and a free allowance. Reversible — only the host manifest
  (`fly.toml`) would change.

## Status

Proposed. The one point most worth a second opinion is the accepted runner
residual risk: it is defensible at demo exposure but is a genuine decision, not a
detail. If the deployment is ever meant to be broadly public, revisit that first.
