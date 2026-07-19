"""MockMate interviewer agent API (Day 2, ADR 0006/0007).

POST /api/session                    -> starts a Session, returns Q1
POST /api/transcribe   (audio file)  -> {transcript}
POST /api/session/{id}/answer        -> judges the answer, advances the Session
POST /api/session/{id}/dsa/run       -> runs candidate code against test cases
POST /api/session/{id}/dsa/submit    -> submits code, gets the interviewer's reaction

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
from pydantic import BaseModel, Field

from .agent import InterviewState, start_session, submit_answer, submit_code, build_graph
from .evaluator import build_evaluator_graph, evaluate_session
from .providers import ProviderError, ProviderUnavailableError, get_provider
from .resume import ResumeError, extract_resume_text
from .runner import RunResult, run_tests, summarize_run
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

# Uploaded resumes, reduced to capped plain text (ADR 0015). In-memory like
# everything else (ADR 0007): anonymous, dies with the process. PII - never log.
_resumes: dict[str, str] = {}


class CreateSessionRequest(BaseModel):
    domain: str
    voice: str = DEFAULT_VOICE
    resume_id: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    first_question: str
    audio_b64: str
    question_number: int
    total_questions: int
    stage: str
    warm_up_source: str  # "resume" | "bank" — the Candidate can tell which interview they got


class AnswerRequest(BaseModel):
    transcript: str
    voice: str = DEFAULT_VOICE


class AnswerResponse(BaseModel):
    reply: str
    audio_b64: str
    phase: str
    question_number: int
    total_questions: int
    stage: str
    dsa: "DsaPayload | None" = None


MAX_CODE_CHARS = 10_000  # a coding-exercise solution, not a novel (TPM guard, ADR 0017)


class DsaPayload(BaseModel):
    """What the editor needs to render a DSA question."""

    function_name: str
    signature: str
    starter_code: str
    test_cases: list[dict]


class TestCaseReport(BaseModel):
    args: list
    expected: object = None
    got: str
    passed: bool


class RunReport(BaseModel):
    status: str  # "ok" | "error" | "timeout"
    error: str | None = None
    passed: int
    total: int
    results: list[TestCaseReport]


class DsaRunRequest(BaseModel):
    code: str = Field(max_length=MAX_CODE_CHARS)


class DsaSubmitRequest(DsaRunRequest):
    voice: str = DEFAULT_VOICE


class DsaSubmitResponse(BaseModel):
    reply: str
    audio_b64: str
    phase: str
    question_number: int
    total_questions: int
    stage: str
    run: RunReport


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


def _stage(state: InterviewState) -> str:
    return "done" if state["phase"] == "done" else state["current_question"]["stage"]


def _dsa_payload(state: InterviewState) -> DsaPayload | None:
    question = state["current_question"]
    if (
        state["phase"] == "done"
        or question.get("stage") != "dsa"
        or "submission" in question
    ):
        return None
    return DsaPayload(
        function_name=question["function_name"],
        signature=question["signature"],
        starter_code=question["starter_code"],
        test_cases=question["test_cases"],
    )


def _run_report(result: RunResult) -> RunReport:
    return RunReport(
        status=result.status,
        error=result.error,
        passed=sum(1 for r in result.results if r.passed),
        total=len(result.results),
        results=[
            TestCaseReport(args=r.args, expected=r.expected, got=r.got, passed=r.passed)
            for r in result.results
        ],
    )


def _current_dsa_question(session_id: str) -> tuple[InterviewState, dict]:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown session")
    question = state["current_question"]
    if state["phase"] == "done" or question.get("stage") != "dsa":
        raise HTTPException(status_code=409, detail="the Session is not on a coding question")
    return state, question


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


@app.post("/api/resume")
async def upload_resume(file: UploadFile):
    data = await file.read()
    try:
        text = extract_resume_text(
            data, file.filename or "", file.content_type or ""
        )
    except ResumeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resume_id = str(uuid.uuid4())
    _resumes[resume_id] = text
    return {"resume_id": resume_id, "characters": len(text)}


@app.post("/api/session", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    if req.domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail=f"unsupported domain {req.domain!r}")

    resume_text = None
    if req.resume_id is not None:
        resume_text = _resumes.get(req.resume_id)
        if resume_text is None:
            raise HTTPException(status_code=404, detail="unknown resume")

    session_id = str(uuid.uuid4())

    warm_up_questions = None
    if resume_text is not None:
        try:
            # Empty list (ScriptedProvider) and ProviderError both mean the
            # same thing here: use the curated fallback. A failed generation
            # never blocks a Session (ADR 0015).
            warm_up_questions = (
                await get_provider().generate_warm_up_questions(resume_text, req.domain)
                or None
            )
        except ProviderError as exc:
            logger.warning(
                "warm-up generation failed for session %s, using the question bank (%s)",
                session_id,
                type(exc).__name__,
            )

    state = start_session(session_id, req.domain, warm_up_questions=warm_up_questions)
    _sessions[session_id] = state

    audio = await synthesize(state["current_question"]["question"], req.voice)
    number, total = _progress(state)
    return CreateSessionResponse(
        session_id=session_id,
        first_question=state["current_question"]["question"],
        audio_b64=base64.b64encode(audio).decode(),
        question_number=number,
        total_questions=total,
        stage=_stage(state),
        warm_up_source="resume" if warm_up_questions else "bank",
    )


@app.post("/api/session/{session_id}/answer", response_model=AnswerResponse)
async def answer(session_id: str, req: AnswerRequest) -> AnswerResponse:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown session")

    current = state["current_question"]
    if current.get("stage") == "dsa" and "submission" not in current:
        raise HTTPException(status_code=409, detail="submit code for this question first")

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
        stage=_stage(state),
        dsa=_dsa_payload(state),
    )


@app.post("/api/session/{session_id}/dsa/run", response_model=RunReport)
async def dsa_run(session_id: str, req: DsaRunRequest) -> RunReport:
    """Run the Candidate's code against the current question's test cases.

    Free iteration: no LLM, no Session state change (ADR 0017)."""
    _, question = _current_dsa_question(session_id)
    result = await asyncio.to_thread(
        run_tests, req.code, question["function_name"], question["test_cases"]
    )
    return _run_report(result)


@app.post("/api/session/{session_id}/dsa/submit", response_model=DsaSubmitResponse)
async def dsa_submit(session_id: str, req: DsaSubmitRequest) -> DsaSubmitResponse:
    """Final Submission: run the tests, get the interviewer's spoken reaction,
    and open the discussion. Once per question (ADR 0017)."""
    state, question = _current_dsa_question(session_id)
    if "submission" in question:
        raise HTTPException(status_code=409, detail="code was already submitted for this question")

    result = await asyncio.to_thread(
        run_tests, req.code, question["function_name"], question["test_cases"]
    )
    try:
        reaction = await get_provider().react_to_code(
            question=question["question"],
            code=req.code,
            results_summary=summarize_run(result),
            history=state["transcript"],
        )
    except ProviderError as exc:
        # State untouched: the Candidate just presses Submit again (ADR 0017).
        logger.warning("code reaction failed for session %s: %s", session_id, type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="the AI provider is temporarily unavailable — please try again",
        ) from exc

    state = submit_code(state, req.code, result, reaction)
    _sessions[session_id] = state

    audio = await synthesize(state["reply"], req.voice)
    number, total = _progress(state)
    return DsaSubmitResponse(
        reply=state["reply"],
        audio_b64=base64.b64encode(audio).decode(),
        phase=_external_phase(state),
        question_number=number,
        total_questions=total,
        stage=_stage(state),
        run=_run_report(result),
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
        if session_id in _evaluations:
            result = _evaluations[session_id]
        else:
            graph = build_evaluator_graph(get_provider())
            result = await evaluate_session(
                graph, session_id, state["domain"], state["completed"]
            )
            # A transient provider failure (rate limit, timeout) should not be
            # baked in forever — only cache once every Score/Assessment call
            # either succeeded or failed deterministically (malformed).
            if not result["retryable_failure"]:
                _evaluations[session_id] = result

    return EvaluationResponse(**{k: v for k, v in result.items() if k != "retryable_failure"})
