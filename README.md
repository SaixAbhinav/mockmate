# MockMate (working title)

A voice-based AI mock interviewer you can run for free — the "$150/month
interview-prep SaaS" genre, rebuilt as an open, self-hostable app.

Speak your answers; an AI interviewer asks questions, probes follow-ups, and
(soon) scores you against rubrics and targets your weak areas.

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

208 passed.

## Design decisions

Every significant decision is recorded in [docs/decisions/](docs/decisions/)
as a short ADR — context, options, choice, consequences.

## Dependencies

Backend: FastAPI, uvicorn, edge-tts, httpx, python-dotenv, pyyaml, langgraph, pypdf,
langchain-core (pinned in `backend/requirements.txt`); pytest, anyio for
tests (`backend/requirements-dev.txt`). Frontend: React via Vite. Coming
later (flagged in advance per repo rules): Chroma, sentence-transformers.
