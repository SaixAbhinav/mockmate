"""MockMate interviewer agent API (Day 2, ADR 0006/0007).

POST /api/session                    -> starts a Session, returns Q1
POST /api/transcribe   (audio file)  -> {transcript}
POST /api/session/{id}/answer        -> judges the answer, advances the Session
POST /api/session/{id}/dsa/run       -> runs candidate code against test cases
POST /api/session/{id}/dsa/submit    -> submits code, gets the interviewer's reaction
POST /api/session/{id}/dsa/snapshot  -> stores the candidate's latest code (no LLM)
POST /api/session/{id}/dsa/check-in  -> the watching interviewer's look at the latest Snapshot

Session state lives in an in-memory dict (ADR 0007): fine for anonymous,
single-process demo traffic; orphaned sessions are known, deferred debt.
"""

import asyncio
import base64
import logging
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import (
    InterviewState,
    build_graph,
    record_coding_chat,
    record_interjection,
    start_session,
    submit_answer,
    submit_code,
)
from .evaluator import build_evaluator_graph, evaluate_session
from .providers import ProviderError, ProviderUnavailableError, WatchDecision, get_provider
from .resume import ResumeError, extract_resume_text
from .runner import RunResult, run_tests, summarize_run
from .session_store import get_store
from .stt import SttUnavailableError, transcribe
from .tts import DEFAULT_VOICE, VOICES, synthesize
from .watcher import (
    CHAT_CAP_REMARK,
    MAX_CHATS_PER_QUESTION,
    OFFER_REMARK,
    check_in_due,
    describe_runs,
    is_stuck,
    note_chat,
    note_check_in,
    note_interjection,
    note_run,
    offer_due,
    record_snapshot,
    start_watch,
)

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

# Sessions and Evaluations live behind `SessionStore` (ADR 0007, ADR 0021).

# One lock per Session. The cache check straddles an await, so without this two
# concurrent requests both miss and both score. React's <StrictMode> makes that a
# certainty in dev, not a theoretical race.
_evaluation_locks: dict[str, asyncio.Lock] = {}

# Uploaded resumes, reduced to capped plain text (ADR 0015). In-memory like
# everything else (ADR 0007): anonymous, dies with the process. PII - never log.
_resumes: dict[str, str] = {}

# The watcher's clock, module-level so tests can monkeypatch time instead of
# sleeping through 75-second cooldowns (ADR 0018).
_now = time.monotonic


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


class SnapshotRequest(BaseModel):
    code: str = Field(max_length=MAX_CODE_CHARS)


class CheckInRequest(BaseModel):
    voice: str = DEFAULT_VOICE


class CheckInResponse(BaseModel):
    action: str  # "silent" | "offer" | "ask" | "hint"
    remark: str = ""
    audio_b64: str = ""


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


class SubmissionTests(BaseModel):
    """The Runner's verdict on a Submission — computed facts, never judged."""

    status: str
    passed: int
    total: int


class DsaQuestionScore(BaseModel):
    question: str
    topic: str
    difficulty: str
    tests: SubmissionTests | None = None  # absent only for the defensive never-submitted case
    code_quality: int | None = None
    approach: int | None = None
    comment: str | None = None
    hints: int = 0
    runs: int = 0
    skipped: bool = False
    unscored: bool = False


class DsaSection(BaseModel):
    """The coding round's half of the Evaluation (ADR 0020)."""

    averages: dict[str, float | None]
    hints_used: int
    questions: list[DsaQuestionScore]


class EvaluationResponse(BaseModel):
    session_id: str
    domain: str
    averages: dict[str, float | None]
    coverage: Coverage
    assessment: str
    strengths: list[str]
    improvements: list[str]
    questions: list[QuestionScore]
    dsa: DsaSection


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


async def _current_dsa_question(session_id: str) -> tuple[InterviewState, dict]:
    state = await get_store().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown session")
    question = state["current_question"]
    if state["phase"] == "done" or question.get("stage") != "dsa":
        raise HTTPException(status_code=409, detail="the Session is not on a coding question")
    return state, question


def _store_watch(state: InterviewState, watch: dict) -> InterviewState:
    return {**state, "current_question": {**state["current_question"], "watch": watch}}


async def _unsubmitted_dsa_question(session_id: str) -> tuple[InterviewState, dict]:
    state, question = await _current_dsa_question(session_id)
    if "submission" in question:
        raise HTTPException(status_code=409, detail="code was already submitted for this question")
    return state, question


async def _spoken_check_in(
    session_id: str, state: InterviewState, watch: dict, action: str, remark: str, voice: str
) -> CheckInResponse:
    """Deliver an interjection: transcript first, then audio (ADR 0018)."""
    state = record_interjection(_store_watch(state, watch), remark)
    await get_store().save(state)
    audio = await synthesize(remark, voice)
    return CheckInResponse(
        action=action, remark=remark, audio_b64=base64.b64encode(audio).decode()
    )


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
    await get_store().save(state)

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
    store = get_store()
    state = await store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown session")

    current = state["current_question"]
    if current.get("stage") == "dsa" and "submission" not in current:
        # Voice is live while coding (ADR 0019): a side conversation, not a
        # judged answer. The graph never runs, nothing advances, and the
        # Submission stays the only way past a coding question.
        watch = current.get("watch") or start_watch(_now())
        code = watch["code"] if watch["code"] is not None else current["starter_code"]
        if watch["chats"] >= MAX_CHATS_PER_QUESTION:
            # The cap keeps chat from being the app's one unmetered LLM
            # surface. A canned spoken redirect, not an error (ADR 0019).
            reply = CHAT_CAP_REMARK
        else:
            try:
                reply = await get_provider().coding_chat(
                    question=current["question"],
                    code=code,
                    history=state["transcript"],
                    utterance=req.transcript,
                )
            except ProviderUnavailableError as exc:
                logger.warning("coding chat unavailable for session %s: %s", session_id, exc)
                raise HTTPException(
                    status_code=503,
                    detail="the AI provider is temporarily unavailable — please try again",
                ) from exc
            watch = note_chat(watch)
        state = record_coding_chat(_store_watch(state, watch), req.transcript, reply)
        await store.save(state)
        audio = await synthesize(reply, req.voice)
        number, total = _progress(state)
        return AnswerResponse(
            reply=reply,
            audio_b64=base64.b64encode(audio).decode(),
            phase=_external_phase(state),
            question_number=number,
            total_questions=total,
            stage=_stage(state),
            dsa=_dsa_payload(state),
        )

    graph = build_graph(get_provider())
    try:
        state = await submit_answer(graph, state, req.transcript)
    except ProviderUnavailableError as exc:
        logger.warning("interviewer unavailable for session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=503,
            detail="the AI provider is temporarily unavailable — please try again",
        ) from exc
    await store.save(state)

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
    state, question = await _current_dsa_question(session_id)
    result = await asyncio.to_thread(
        run_tests, req.code, question["function_name"], question["test_cases"]
    )
    report = _run_report(result)
    if "submission" not in question:
        # Watcher telemetry, not interview movement (ADR 0018): the run stays
        # free iteration, but the watcher sees how it is going.
        watch = note_run(
            question.get("watch") or start_watch(_now()),
            passed=report.passed,
            total=report.total,
        )
        await get_store().save(_store_watch(state, watch))
    return report


@app.post("/api/session/{session_id}/dsa/submit", response_model=DsaSubmitResponse)
async def dsa_submit(session_id: str, req: DsaSubmitRequest) -> DsaSubmitResponse:
    """Final Submission: run the tests, get the interviewer's spoken reaction,
    and open the discussion. Once per question (ADR 0017)."""
    state, question = await _unsubmitted_dsa_question(session_id)

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
    await get_store().save(state)

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


@app.post("/api/session/{session_id}/dsa/snapshot")
async def dsa_snapshot(session_id: str, req: SnapshotRequest):
    """Store the Candidate's latest code for the watching interviewer.

    Sent on typing pauses; no LLM, no interview movement. The first
    Snapshot starts the watcher's clock (ADR 0018)."""
    state, question = await _unsubmitted_dsa_question(session_id)
    now = _now()
    watch = record_snapshot(question.get("watch") or start_watch(now), req.code, now)
    await get_store().save(_store_watch(state, watch))
    return {"received": True}


@app.post("/api/session/{session_id}/dsa/check-in", response_model=CheckInResponse)
async def dsa_check_in(session_id: str, req: CheckInRequest) -> CheckInResponse:
    """The watching interviewer's look at the latest Snapshot (ADR 0018).

    Polled by the frontend. The deterministic Offer fires first when due;
    otherwise the server-side gates (typing-anchored interval, cooldown,
    cap) decide when a poll becomes an LLM look. Cooldowns and provider
    failures both answer silent - a poll never surfaces an error."""
    state, question = await _unsubmitted_dsa_question(session_id)
    now = _now()
    watch = question.get("watch") or start_watch(now)

    if offer_due(watch, now):
        # Two minutes of silence needs no model to interpret (ADR 0018).
        watch = note_check_in(watch, question["starter_code"], now)
        watch = note_interjection(watch, now, action="offer")
        return await _spoken_check_in(session_id, state, watch, "offer", OFFER_REMARK, req.voice)

    if not check_in_due(watch, now):
        await get_store().save(_store_watch(state, watch))  # persists a fresh watch
        return CheckInResponse(action="silent")

    code = watch["code"] if watch["code"] is not None else question["starter_code"]
    stuck = is_stuck(watch, question["starter_code"])
    try:
        decision = await get_provider().watch_code(
            question=question["question"],
            code=code,
            stuck=stuck,
            seconds_elapsed=now - watch["started_at"],
            runs_summary=describe_runs(watch),
        )
    except ProviderError as exc:
        # A watcher that can't think stays quiet (ADR 0018). Never log the code.
        logger.warning("check-in failed for session %s: %s", session_id, type(exc).__name__)
        decision = WatchDecision(action="silent", remark="")

    # The look is recorded even on failure, so a failing provider is not
    # hammered again on the next poll.
    watch = note_check_in(watch, code, now)
    if decision.action == "silent":
        await get_store().save(_store_watch(state, watch))
        return CheckInResponse(action="silent")

    watch = note_interjection(watch, now, decision.action)
    return await _spoken_check_in(
        session_id, state, watch, decision.action, decision.remark, req.voice
    )


@app.get("/api/session/{session_id}/evaluation", response_model=EvaluationResponse)
async def evaluation(session_id: str) -> EvaluationResponse:
    # Evaluations are cached per Session: the Evaluation is stable once a Session
    # is finished, and re-running it would re-bill nine LLM calls on every refresh.
    store = get_store()
    state = await store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown session")
    if state["phase"] != "done":
        raise HTTPException(status_code=409, detail="the Session is not finished yet")

    # setdefault does not await, so it is atomic on the event loop.
    lock = _evaluation_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        result = await store.get_evaluation(session_id)
        if result is None:
            graph = build_evaluator_graph(get_provider())
            result = await evaluate_session(
                graph, session_id, state["domain"], state["completed"]
            )
            # A transient provider failure (rate limit, timeout) should not be
            # baked in forever — only cache once every Score/Assessment call
            # either succeeded or failed deterministically (malformed).
            if not result["retryable_failure"]:
                await store.save_evaluation(session_id, result)

    return EvaluationResponse(**{k: v for k, v in result.items() if k != "retryable_failure"})
