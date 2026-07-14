"""MockMate interviewer agent API (Day 2, ADR 0006/0007).

POST /api/session                    -> starts a Session, returns Q1
POST /api/transcribe   (audio file)  -> {transcript}
POST /api/session/{id}/answer        -> judges the answer, advances the Session

Session state lives in an in-memory dict (ADR 0007): fine for anonymous,
single-process demo traffic; orphaned sessions are known, deferred debt.
"""

import base64
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import InterviewState, start_session, submit_answer, build_graph
from .providers import get_provider
from .stt import SttUnavailableError, transcribe
from .tts import DEFAULT_VOICE, VOICES, synthesize

load_dotenv()

app = FastAPI(title="MockMate")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_DOMAINS = {"ml_genai"}

_sessions: dict[str, InterviewState] = {}


class CreateSessionRequest(BaseModel):
    domain: str
    voice: str = DEFAULT_VOICE


class CreateSessionResponse(BaseModel):
    session_id: str
    first_question: str
    audio_b64: str
    question_number: int
    total_questions: int


class AnswerRequest(BaseModel):
    transcript: str
    voice: str = DEFAULT_VOICE


class AnswerResponse(BaseModel):
    reply: str
    audio_b64: str
    phase: str
    question_number: int
    total_questions: int


def _progress(state: InterviewState) -> tuple[int, int]:
    in_progress = 0 if state["phase"] == "done" else 1
    total = len(state["completed"]) + len(state["queue"]) + in_progress
    number = len(state["completed"]) + in_progress
    return number, total


def _external_phase(state: InterviewState) -> str:
    # "asking" is an internal detail of having just moved to a new question;
    # the API surfaces it as "advancing" per the answer-endpoint contract.
    return "advancing" if state["phase"] == "asking" else state["phase"]


@app.get("/api/health")
async def health():
    return {"status": "ok", "provider": get_provider().name}


@app.get("/api/voices")
async def voices():
    return {"voices": VOICES, "default": DEFAULT_VOICE}


@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile):
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="empty audio upload")
    try:
        text = await transcribe(
            audio, file.filename or "answer.webm", file.content_type or "audio/webm"
        )
    except SttUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"transcript": text}


@app.post("/api/session", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    if req.domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail=f"unsupported domain {req.domain!r}")

    session_id = str(uuid.uuid4())
    state = start_session(session_id, req.domain)
    _sessions[session_id] = state

    audio = await synthesize(state["current_question"]["question"], req.voice)
    number, total = _progress(state)
    return CreateSessionResponse(
        session_id=session_id,
        first_question=state["current_question"]["question"],
        audio_b64=base64.b64encode(audio).decode(),
        question_number=number,
        total_questions=total,
    )


@app.post("/api/session/{session_id}/answer", response_model=AnswerResponse)
async def answer(session_id: str, req: AnswerRequest) -> AnswerResponse:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown session")

    graph = build_graph(get_provider())
    state = await submit_answer(graph, state, req.transcript)
    _sessions[session_id] = state

    audio = await synthesize(state["reply"], req.voice)
    number, total = _progress(state)
    return AnswerResponse(
        reply=state["reply"],
        audio_b64=base64.b64encode(audio).decode(),
        phase=_external_phase(state),
        question_number=number,
        total_questions=total,
    )
