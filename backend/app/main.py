"""MockMate interviewer agent API (Day 2, ADR 0006/0007).

POST /api/session                    -> starts a Session, returns Q1
POST /api/transcribe   (audio file)  -> {transcript}
POST /api/session/{id}/answer        -> judges the answer, advances the Session

Session state lives in an in-memory dict (ADR 0007): fine for anonymous,
single-process demo traffic; orphaned sessions are known, deferred debt.
"""

import asyncio
import base64
import logging
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import InterviewState, start_session, submit_answer, build_graph
from .evaluator import build_evaluator_graph, evaluate_session
from .providers import ProviderUnavailableError, get_provider
from .stt import SttUnavailableError, transcribe
from .tts import DEFAULT_VOICE, VOICES, synthesize

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="MockMate")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_DOMAINS = {"ml_genai"}

_sessions: dict[str, InterviewState] = {}

# Evaluations are cached per Session: the Evaluation is stable once a Session is
# finished, and re-running it would re-bill nine LLM calls on every refresh.
_evaluations: dict[str, dict] = {}

# One lock per Session. The cache check straddles an await, so without this two
# concurrent requests both miss and both score. React's <StrictMode> makes that a
# certainty in dev, not a theoretical race.
_evaluation_locks: dict[str, asyncio.Lock] = {}


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


class QuestionScore(BaseModel):
    question: str
    topic: str
    difficulty: str
    correctness: int | None = None
    depth: int | None = None
    clarity: int | None = None
    comment: str | None = None
    skipped: bool = False
    unscored: bool = False


class Coverage(BaseModel):
    answered: int
    total: int


class EvaluationResponse(BaseModel):
    session_id: str
    domain: str
    averages: dict[str, float | None]
    coverage: Coverage
    assessment: str
    strengths: list[str]
    improvements: list[str]
    questions: list[QuestionScore]


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
    try:
        state = await submit_answer(graph, state, req.transcript)
    except ProviderUnavailableError as exc:
        logger.warning("interviewer unavailable for session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=503,
            detail="the AI provider is temporarily unavailable — please try again",
        ) from exc
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


@app.get("/api/session/{session_id}/evaluation", response_model=EvaluationResponse)
async def evaluation(session_id: str) -> EvaluationResponse:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown session")
    if state["phase"] != "done":
        raise HTTPException(status_code=409, detail="the Session is not finished yet")

    # setdefault does not await, so it is atomic on the event loop.
    lock = _evaluation_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        if session_id not in _evaluations:
            graph = build_evaluator_graph(get_provider())
            _evaluations[session_id] = await evaluate_session(
                graph, session_id, state["domain"], state["completed"]
            )
    return EvaluationResponse(**_evaluations[session_id])
