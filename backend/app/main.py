"""Callback interviewer agent API (Day 2, ADR 0006/0007).

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
import os
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import (
    InterviewState,
    build_graph,
    current_watch,
    record_coding_chat,
    record_interjection,
    set_watch,
    start_session,
    submit_answer,
    submit_code,
)
from .evaluator import build_evaluator_graph, evaluate_session
from .providers import ProviderError, ProviderUnavailableError, get_provider
from .questions import FALLBACK_DOMAIN
from .resume import ResumeError, extract_resume_text, vocabulary_digest
from .runner import RunResult, run_tests, summarize_run
from .secrets import load_secrets_from_ssm
from .session_store import get_store
from .stt import SttUnavailableError, transcribe
from .tts import DEFAULT_VOICE, VOICES, synthesize
from .watcher import (
    CHAT_CAP_REMARK,
    MAX_CHATS_PER_QUESTION,
    check_in,
    note_chat,
    note_reply,
    observe_run,
    observe_snapshot,
)

load_dotenv()
# On Lambda (LOAD_SECRETS_FROM_SSM=1, infra/lambda.tf) this fills in
# GROQ_API_KEY/GEMINI_API_KEY from SSM; everywhere else (local .env, Render)
# it's a no-op (ADR 0029).
load_secrets_from_ssm()

def _log_level() -> int:
    """Resolve LOG_LEVEL, tolerating case and nonsense.

    basicConfig would raise on a lowercase or unknown name, and it raises at
    import — so a stray `LOG_LEVEL=info` would take the whole app down at
    startup rather than degrade to a default.
    """
    name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


# uvicorn configures its own loggers, not ours: without this the app's logger
# propagates to a handler-less root at the default WARNING level, so every
# logger.info() in this package is silently discarded.
logging.basicConfig(
    level=_log_level(),
    # ASCII separator on purpose: an em dash here renders as a replacement
    # character in a cp1252 Windows console.
    format="%(levelname)s:     %(name)s - %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Callback")


def _cors_origins() -> list[str]:
    """Resolve the allowed browser origins.

    Production serves the SPA from a static site that *rewrites* /api/* to this
    service, so the browser sees one origin and needs no CORS at all (ADR 0025).
    This stays configurable so a deployed image carries no hardcoded dev origin,
    and so the app still works if that rewrite is ever swapped for a direct
    cross-origin call.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["http://localhost:5173"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sessions and Evaluations live behind `SessionStore` (ADR 0007, ADR 0021).

# Uploaded resumes, reduced to capped plain text (ADR 0015). In-memory like
# everything else (ADR 0007): anonymous, dies with the process. PII - never log.
_resumes: dict[str, str] = {}

# Per-Session vocabulary digests priming speech-to-text (ADR 0026). Kept beside
# _resumes rather than in the graph state: it is a transcription concern, not
# something the interview graph or the evaluator ever reads. Same in-memory
# posture and the same deferred-cleanup debt as _resumes (ADR 0007/0015).
_stt_prompts: dict[str, str] = {}

# The watcher's clock, module-level so tests can monkeypatch time instead of
# sleeping through 75-second cooldowns (ADR 0018).
_now = time.monotonic


class CreateSessionRequest(BaseModel):
    voice: str = DEFAULT_VOICE
    resume_id: str | None = None
    # Set only after the Candidate has been told generation failed and chose to
    # continue anyway (ADR 0023). Never defaulted true.
    allow_bank_fallback: bool = False


class CreateSessionResponse(BaseModel):
    session_id: str
    first_question: str
    audio_b64: str
    question_number: int
    total_questions: int
    stage: str
    warm_up_source: str  # "resume" | "bank" — the Candidate can tell which interview they got
    domain: str  # inferred from the resume, or the fallback bank's own (ADR 0023)


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

    # `prompt` is the same text the interviewer speaks, so the editor can pin
    # the question above the code instead of making the candidate scroll the
    # transcript back to it. The spoken turn stays in history deliberately.
    prompt: str
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


def _stopwatch():
    """Start a wall-clock timer; call the returned function for elapsed ms.

    Turn latency is otherwise only measured client-side and end-to-end, which
    cannot say whether a slow turn was the interviewer's LLM call or speech
    synthesis. These two are awaited serially on every turn, so splitting them
    is the difference between a guess and a diagnosis.
    """
    started = time.perf_counter()
    return lambda: (time.perf_counter() - started) * 1000


def _log_turn(session_id: str, stage: str, llm_ms: float, tts_ms: float) -> None:
    logger.info(
        "turn timing session=%s stage=%s llm_ms=%.0f tts_ms=%.0f total_ms=%.0f",
        session_id,
        stage,
        llm_ms,
        tts_ms,
        llm_ms + tts_ms,
    )


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
        prompt=question["question"],
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


async def _unsubmitted_dsa_question(session_id: str) -> tuple[InterviewState, dict]:
    state, question = await _current_dsa_question(session_id)
    if "submission" in question:
        raise HTTPException(status_code=409, detail="code was already submitted for this question")
    return state, question


async def _spoken_check_in(
    session_id: str, state: InterviewState, watch: dict, action: str, remark: str, voice: str
) -> CheckInResponse:
    """Deliver an interjection: transcript first, then audio (ADR 0018)."""
    state = record_interjection(set_watch(state, watch), remark)
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
async def transcribe_audio(file: UploadFile, session_id: str | None = Form(None)):
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="empty audio upload")
    # Optional on purpose: voice input has to keep working before a Session
    # exists, without a resume, and in the keyless demo (ADR 0026). An unknown
    # id degrades to no prompt rather than failing the Turn.
    prompt = _stt_prompts.get(session_id) if session_id else None
    try:
        text = await transcribe(
            audio,
            file.filename or "answer.webm",
            file.content_type or "audio/webm",
            prompt=prompt,
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
    resume_text = None
    if req.resume_id is not None:
        resume_text = _resumes.get(req.resume_id)
        if resume_text is None:
            raise HTTPException(status_code=404, detail="unknown resume")

    session_id = str(uuid.uuid4())

    warm_up = None
    # Skip generation entirely once the Candidate has accepted the bank: they
    # asked for the general interview, so retrying could hand them a tailored
    # one against their choice, and costs a second provider call on the failure
    # path we already know about (ADR 0023).
    if resume_text is not None and not req.allow_bank_fallback:
        try:
            # Empty questions (ScriptedProvider) and ProviderError both mean the
            # same thing here: no tailored interview is available (ADR 0015).
            generated = await get_provider().generate_warm_up_questions(resume_text)
            warm_up = generated if generated.questions else None
        except ProviderError as exc:
            logger.warning(
                "warm-up generation failed for session %s (%s)",
                session_id,
                type(exc).__name__,
            )

    # A Candidate who uploaded a resume was promised a tailored interview. If we
    # cannot give them one, say so before the Session exists rather than after
    # it has already started (ADR 0023) - they choose the general interview.
    if resume_text is not None and warm_up is None and not req.allow_bank_fallback:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "generation_unavailable",
                "fallback_domain": FALLBACK_DOMAIN,
                "message": (
                    "We couldn't tailor this interview to your resume. We can "
                    "run a general ML/GenAI interview instead."
                ),
            },
        )

    domain = warm_up.domain if warm_up is not None else FALLBACK_DOMAIN
    state = start_session(
        session_id,
        domain,
        warm_up_questions=warm_up.questions if warm_up is not None else None,
    )
    await get_store().save(state)

    # Built once here rather than per Turn, keeping the work off the
    # conversational critical path (ADR 0015's argument, reapplied). Derived
    # from the resume itself, so it survives a bank fallback - the Candidate's
    # name and projects are worth priming even when generation failed.
    if resume_text is not None:
        digest = vocabulary_digest(resume_text)
        if digest:
            _stt_prompts[session_id] = digest

    audio = await synthesize(state["current_question"]["question"], req.voice)
    number, total = _progress(state)
    return CreateSessionResponse(
        session_id=session_id,
        first_question=state["current_question"]["question"],
        audio_b64=base64.b64encode(audio).decode(),
        question_number=number,
        total_questions=total,
        stage=_stage(state),
        warm_up_source="resume" if warm_up is not None else "bank",
        domain=domain,
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
        watch = current_watch(state, _now())
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
        # Both branches speak, so both start the watcher's cooldown (ADR 0028):
        # the canned redirect is still the Interviewer talking. Stamped here
        # rather than at the top of the turn because the LLM call sits in
        # between, and the cooldown runs from when the Candidate is spoken to.
        watch = note_reply(watch, _now())
        state = record_coding_chat(set_watch(state, watch), req.transcript, reply)
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
    llm = _stopwatch()
    try:
        state = await submit_answer(graph, state, req.transcript)
    except ProviderUnavailableError as exc:
        logger.warning("interviewer unavailable for session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=503,
            detail="the AI provider is temporarily unavailable — please try again",
        ) from exc
    llm_ms = llm()
    await store.save(state)

    tts = _stopwatch()
    audio = await synthesize(state["reply"], req.voice)
    _log_turn(session_id, _stage(state), llm_ms, tts())
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
        watch = observe_run(
            current_watch(state, _now()),
            passed=report.passed,
            total=report.total,
        )
        await get_store().save(set_watch(state, watch))
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
    state, _ = await _unsubmitted_dsa_question(session_id)
    now = _now()
    watch = observe_snapshot(current_watch(state, now), req.code, now)
    await get_store().save(set_watch(state, watch))
    return {"received": True}


@app.post("/api/session/{session_id}/dsa/check-in", response_model=CheckInResponse)
async def dsa_check_in(session_id: str, req: CheckInRequest) -> CheckInResponse:
    """The watching interviewer's look at the latest Snapshot (ADR 0018).

    Polled by the frontend; the policy itself lives in `watcher.check_in`
    (ADR 0027). This endpoint supplies the clock and the Provider, stores
    the watch the policy hands back, and speaks when it says to."""
    state, question = await _unsubmitted_dsa_question(session_id)
    now = _now()
    watch, decision = await check_in(
        current_watch(state, now),
        question_text=question["question"],
        starter_code=question["starter_code"],
        now=now,
        provider=get_provider(),
    )
    if decision.failure is not None:
        # Check-ins fail silent by design, so this line is the only trace a
        # Provider is failing - it belongs where the Session id is (ADR 0027).
        logger.warning("check-in failed for session %s: %s", session_id, decision.failure)
    if decision.action == "silent":
        await get_store().save(set_watch(state, watch))  # persists a fresh watch
        return CheckInResponse(action="silent")
    return await _spoken_check_in(
        session_id, state, watch, decision.action, decision.remark, req.voice
    )


async def _await_evaluation(store, session_id: str) -> dict | None:
    """Poll for the winning request's saved Evaluation (ADR 0029 loser policy:
    a request that loses `claim_evaluation` waits for the winner instead of
    recomputing). Returns the Evaluation, or None if it does not appear within
    the bounded wait (e.g. the winner hit a retryable failure and released
    without saving)."""
    wait_seconds = float(os.getenv("MOCKMATE_EVAL_WAIT_SECONDS", "30.0"))
    deadline = asyncio.get_event_loop().time() + wait_seconds
    while True:
        result = await store.get_evaluation(session_id)
        if result is not None:
            return result
        if asyncio.get_event_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.1)


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

    # `claim_evaluation` (ADR 0029, Race A) replaces the in-process
    # `_evaluation_locks`: it is the storage-backed guard that still works
    # across Lambda containers, where a plain `asyncio.Lock` cannot coordinate.
    result = await store.get_evaluation(session_id)  # fast path: already cached
    if result is None:
        if await store.claim_evaluation(session_id):  # we won the claim - compute
            try:
                graph = build_evaluator_graph(get_provider())
                result = await evaluate_session(
                    graph, session_id, state["domain"], state["completed"]
                )
            except BaseException:
                # Unexpected failure: release the claim so a later request can
                # retry, then propagate - swallowing it would wedge the Session.
                await store.release_evaluation_claim(session_id)
                raise
            # A transient provider failure (rate limit, timeout) should not be
            # baked in forever — only cache once every Score/Assessment call
            # either succeeded or failed deterministically (malformed).
            if result["retryable_failure"]:
                await store.release_evaluation_claim(session_id)
            else:
                await store.save_evaluation(session_id, result)
        else:  # we lost the claim - the winner is computing, so wait for it
            result = await _await_evaluation(store, session_id)
            if result is None:
                raise HTTPException(
                    status_code=503, detail="evaluation still in progress, please retry"
                )

    return EvaluationResponse(**{k: v for k, v in result.items() if k != "retryable_failure"})
