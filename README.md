# MockMate (working title)

A voice-based AI mock interviewer you can run for free — the "$150/month
interview-prep SaaS" genre, rebuilt as an open, self-hostable app.

Speak your answers; an AI interviewer asks questions, probes follow-ups, and
(soon) scores you against rubrics and targets your weak areas.

**Status: walking skeleton.** One spoken Q&A turn works end to end:
browser mic → speech-to-text → LLM interviewer → neural TTS reply.

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

Open http://localhost:5173 in Chrome or Edge (voice input needs their speech
recognition; other browsers can use the text box).

## LLM setup (optional)

With no API key the app runs a scripted demo interviewer. For a real one,
copy `backend/.env.example` to `backend/.env` and add a free-tier key from
[Groq](https://console.groq.com) or [Google AI Studio](https://aistudio.google.com).

## Design decisions

Every significant decision is recorded in [docs/decisions/](docs/decisions/)
as a short ADR — context, options, choice, consequences.

## Dependencies

Backend: FastAPI, uvicorn, edge-tts, httpx, python-dotenv (pinned in
`backend/requirements.txt`). Frontend: React via Vite. Coming later (flagged
in advance per repo rules): LangGraph, Chroma, sentence-transformers.
