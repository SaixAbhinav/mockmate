# MockMate (working title)

A voice-based AI mock interviewer you can run for free — the "$150/month
interview-prep SaaS" genre, rebuilt as an open, self-hostable app.

Speak your answers; an AI interviewer asks questions, probes follow-ups, and
(soon) scores you against rubrics and targets your weak areas.

**Status: evaluator agent.** A full mock interview runs end to end — pick a
domain, work through a question queue, get probed or clarified on shallow or
off-topic answers, reach a wrap-up — and then get scored: every answer rated on
correctness, depth, and clarity, with per-question feedback and an overall
assessment.

## Run it

Backend (Python 3.11+):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
uvicorn app.main:app --port 8000
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
pip install -r requirements-dev.txt
pytest
```

72 passed.

## Design decisions

Every significant decision is recorded in [docs/decisions/](docs/decisions/)
as a short ADR — context, options, choice, consequences.

## Dependencies

Backend: FastAPI, uvicorn, edge-tts, httpx, python-dotenv, pyyaml, langgraph,
langchain-core (pinned in `backend/requirements.txt`); pytest, anyio for
tests (`backend/requirements-dev.txt`). Frontend: React via Vite. Coming
later (flagged in advance per repo rules): Chroma, sentence-transformers.
