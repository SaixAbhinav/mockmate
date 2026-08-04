# Callback

> Voice interview practice, in the open.

[![CI](https://github.com/SaixAbhinav/mockmate/actions/workflows/ci.yml/badge.svg)](https://github.com/SaixAbhinav/mockmate/actions/workflows/ci.yml)

A voice-based AI interviewer you can run for free — the "$150/month
interview-prep SaaS" genre, rebuilt as an open, self-hostable app.

Speak your answers; an AI interviewer asks questions, probes follow-ups, and
scores you against rubrics.

**Status: phased interview.** A Session now runs like a real interview's
opening: a "tell me about yourself" intro, then a warm-up round grounded in
your uploaded resume (PDF or text, optional) — with probing and clarifying
follow-ups throughout — then a coding round (2 Python questions run against
test cases in a sandboxed subprocess; the interviewer reacts to the results
and probes your approach), then a wrap-up and a scored Evaluation covering
both halves: rubric scores for the spoken rounds, and for the coding round
the real test results plus judged code quality and approach, with hints
used reported honestly. During the
coding round the interviewer watches the code: typing-anchored check-ins with
cooldowns, an invitation to ask questions after two silent minutes, and a
hint when you're stuck or repeatedly failing the tests — and you can talk to
it while coding, not just after submitting. With both a Groq and a Gemini
key configured, provider failures fail over automatically.

## Run it

Backend (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv venv
uv pip install -r requirements.txt
uv run uvicorn app.main:app --port 8000
```

Frontend (Node 20+):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — works in any browser (speech-to-text is
server-side now, not the browser's own speech API); the text box is always
available as a fallback.

## LLM setup (optional)

With no API key the app runs a scripted demo interviewer (walks the question
queue, never probes). For a real one, copy `backend/.env.example` to
`backend/.env` and add a free-tier key from
[Groq](https://console.groq.com) or [Google AI Studio](https://aistudio.google.com).
With **both** keys set, Groq is the primary and any call it cannot serve
(rate limit, outage) is retried once against Gemini automatically.
The same `GROQ_API_KEY` also powers voice transcription (Whisper); without it,
voice input is unavailable and the text box is the only way to answer.

## Tests

```bash
cd backend
uv venv
uv pip install -r requirements-dev.txt
uv run pytest
```

284 passed.

## Generating questions (dev chore)

The question banks are grown offline, not at runtime ([ADR 0024](docs/decisions/0024-offline-question-generation.md)).
A generator asks a provider for coding questions on a topic, runs them through
machine gates — schema, spoken length, de-duplication, and a correctness check
that executes a throwaway reference solution against the emitted test cases in
the sandboxed runner — and appends the survivors to a gitignored staging file
for you to review by hand into `backend/app/questions/dsa.yaml`.

```bash
cd backend
# coding questions (schema + length + dedupe + runner-correctness gate)
GROQ_API_KEY=... uv run python -m scripts.generate_dsa --topic arrays --count 5
# conceptual warm-up questions (no runner gate — nothing machine-testable)
GROQ_API_KEY=... uv run python -m scripts.generate_warm_up --topic rag --count 5
```

Each writes to a gitignored `*.staging.yaml` (never the bank directly) and
prints what it kept and why it dropped the rest. Reviewing is deletion, not
authorship.

## Deploying

Deployed as two Render services behind one origin
([ADR 0025](docs/decisions/0025-deploy-render-static-plus-api.md)): an always-on
static site serving the SPA, which rewrites `/api/*` to a Docker web service
running the API. The browser only ever sees one origin, so there is no CORS in
production — the same thing `vite.config.js` does with a proxy in development.

1. Push this repo to GitHub and create a **Blueprint** on Render pointing at
   `render.yaml`.
2. Set `GROQ_API_KEY` on the `mockmate-api` service when prompted (it is
   `sync: false`, so it is never stored in git). Without it the app still runs,
   using the scripted demo interviewer.
3. After the API's first deploy, copy its real URL into the static site's
   `/api/*` rewrite destination in `render.yaml` and redeploy. Render subdomains
   are globally unique, so if `mockmate-api` is taken your service gets a
   different name — use whatever URL Render actually assigned. Until this step
   the rewrite points at a host that may not exist, so expect API calls to fail
   on the very first deploy.
4. **Smoke-test a POST** — upload a résumé on the live site. If it fails while
   the page itself loads fine, the rewrite is not proxying request bodies: set
   `VITE_API_BASE` on the static site to the API's URL and `CORS_ORIGINS` on the
   API to the static site's URL, then redeploy both. The SPA then calls the API
   directly and no rewrite is involved.

The API runs on Render's free tier, so it **sleeps after 15 minutes idle** and
takes 30–60s to wake. The static site never sleeps, so the page always loads
instantly, and the start screen pings `/api/health` on mount to wake the API
while you read. Sessions are in-memory
([ADR 0007](docs/decisions/0007-session-state-in-memory.md)), so a redeploy ends
any interview in progress.

You can also run the container by itself:

```bash
docker build -t mockmate-api .
docker run --rm -p 8080:8080 -e PORT=8080 -e GROQ_API_KEY=... mockmate-api
```

## Design decisions

Every significant decision is recorded in [docs/decisions/](docs/decisions/)
as a short ADR — context, options, choice, consequences.

## Dependencies

Backend: FastAPI, uvicorn, edge-tts, httpx, python-dotenv, pyyaml, langgraph, pypdf,
langchain-core (pinned in `backend/requirements.txt`); pytest, anyio for
tests (`backend/requirements-dev.txt`). Frontend: React via Vite. Coming
later (flagged in advance per repo rules): Chroma, sentence-transformers.
