"""Check-in policy for the watching interviewer (ADR 0012/0018).

The policy over a plain "watch" dict that lives on the current DSA
question (next to "submission"): the caller supplies the clock and the
Provider, `check_in` decides (ADR 0027). The gates it composes -
offer_due, check_in_due, is_stuck - stay pure, so every cooldown rule is
still a one-line unit test.

Two clocks: started_at is when the question appeared (the Offer's clock -
120 s of silence earns an invitation to ask for clarification), and
typing_started_at is when engagement began (the watcher's clock - the
first LLM look is one interval after that). Reading is never watched.

Only the latest Snapshot is kept - stuck detection needs the code the
watcher saw at its last look, not a history.

The Watcher never touches InterviewState: it returns the updated watch
and a decision, and the caller stores, speaks and answers the poll.
"""

from dataclasses import dataclass

from .providers import LLMProvider, ProviderError, WatchDecision

CHECK_IN_INTERVAL_SECONDS = 75.0  # ADR 0012's ~60-90 s, split down the middle
INTERJECTION_COOLDOWN_SECONDS = 90.0
MAX_INTERJECTIONS_PER_QUESTION = 3
OFFER_AFTER_SECONDS = 120.0
MAX_CHATS_PER_QUESTION = 15

# Deterministic spoken lines: no model is needed to know that two minutes
# of silence deserves an invitation, or that the 16th chat can wait.
OFFER_REMARK = (
    "Take your time. But if anything about the problem is unclear, "
    "ask me - I'm happy to clarify."
)
CHAT_CAP_REMARK = (
    "Let's focus on the code for now - submit when you're ready and "
    "we can talk it through properly."
)


def start_watch(now: float) -> dict:
    """A fresh watch for the coding question that just became current."""
    return {
        "started_at": now,
        "typing_started_at": None,  # stamped by the first Snapshot
        "code": None,  # latest Snapshot; None until the Candidate types
        "last_checked_code": None,  # what the watcher saw at its last look
        "last_check_at": None,
        "last_spoke_at": None,
        "interjections": 0,
        "hints": 0,
        "chats": 0,
        "runs": 0,
        "last_passed": None,
        "last_total": None,
    }


def observe_snapshot(watch: dict, code: str, now: float) -> dict:
    """The Candidate paused typing; keep only the latest code. The first
    Snapshot starts the watcher's clock (ADR 0018)."""
    typing_started = watch["typing_started_at"]
    return {
        **watch,
        "code": code,
        "typing_started_at": typing_started if typing_started is not None else now,
    }


def offer_due(watch: dict, now: float) -> bool:
    """The deterministic Offer (ADR 0018): the Candidate has typed nothing,
    nothing has been said yet, and the grace has passed."""
    return (
        watch["typing_started_at"] is None
        and watch["interjections"] == 0
        and now - watch["started_at"] >= OFFER_AFTER_SECONDS
    )


def check_in_due(watch: dict, now: float) -> bool:
    """Whether the watcher may take an LLM look now (ADR 0018 cooldowns).

    The first look anchors on typing_started_at - a Candidate who has never
    typed gets the Offer instead, never a cold LLM look."""
    if watch["interjections"] >= MAX_INTERJECTIONS_PER_QUESTION:
        return False
    if (
        watch["last_spoke_at"] is not None
        and now - watch["last_spoke_at"] < INTERJECTION_COOLDOWN_SECONDS
    ):
        return False
    if watch["last_check_at"] is not None:
        return now - watch["last_check_at"] >= CHECK_IN_INTERVAL_SECONDS
    if watch["typing_started_at"] is None:
        return False  # the Offer owns the never-typed case
    return now - watch["typing_started_at"] >= CHECK_IN_INTERVAL_SECONDS


def _normalized(code: str) -> str:
    return "".join(code.split())


def is_stuck(watch: dict, starter_code: str) -> bool:
    """No meaningful edit since the watcher's last look (ADR 0012's
    no-progress trigger). Whitespace-insensitive: reindenting is not
    progress. Before the first look the baseline is the starter code."""
    current = watch["code"] if watch["code"] is not None else starter_code
    baseline = (
        watch["last_checked_code"]
        if watch["last_checked_code"] is not None
        else starter_code
    )
    return _normalized(current) == _normalized(baseline)


def note_check_in(watch: dict, code: str, now: float) -> dict:
    """Record a look at `code` - whether or not the watcher spoke."""
    return {**watch, "last_check_at": now, "last_checked_code": code}


def note_interjection(watch: dict, now: float, action: str) -> dict:
    """Record that the watcher spoke. Hints are counted separately: the
    future DSA-scoring day wants "hints used" (ADR 0012), and an Offer or
    an ask gives no help away."""
    return {
        **watch,
        "last_spoke_at": now,
        "interjections": watch["interjections"] + 1,
        "hints": watch["hints"] + (1 if action == "hint" else 0),
    }


def observe_run(watch: dict, passed: int, total: int) -> dict:
    """Run telemetry (ADR 0018): catches the churning Candidate whose code
    keeps changing but whose tests keep failing - invisible to is_stuck."""
    return {
        **watch,
        "runs": watch["runs"] + 1,
        "last_passed": passed,
        "last_total": total,
    }


def note_chat(watch: dict) -> dict:
    """Count a while-coding exchange toward MAX_CHATS_PER_QUESTION."""
    return {**watch, "chats": watch["chats"] + 1}


def describe_runs(watch: dict) -> str:
    """The run summary for the watch prompt - what a real interviewer
    perceives: are they getting anywhere?"""
    if watch["runs"] == 0:
        return "The candidate has not run the tests yet."
    return (
        f"The candidate has run the tests {watch['runs']} time(s); "
        f"the latest run passed {watch['last_passed']} of "
        f"{watch['last_total']} cases."
    )


def tally(watch: dict) -> dict:
    """The counts the completed record carries into the Evaluation (ADR
    0018/0020), so no other module indexes raw watch keys (ADR 0027)."""
    return {
        "interjections": watch["interjections"],
        "hints": watch["hints"],
        "chats": watch["chats"],
        "runs": watch["runs"],
    }


@dataclass(frozen=True)
class CheckIn:
    """What one Check-in came to, mirroring WatchDecision (ADR 0018).

    Distinct from it because two of the actions are the policy's own: the
    deterministic Offer costs no LLM call, and a Provider that cannot
    answer collapses to silence."""

    action: str  # "silent" | "offer" | "ask" | "hint"
    remark: str
    # The Provider's exception class name when the look could not be taken.
    # To the Candidate a failed look and a closed gate are both silence, so
    # the action cannot carry the difference - but the caller needs it to
    # log a failing Provider against the Session it happened in (ADR 0027).
    failure: str | None = None


async def check_in(
    watch: dict,
    *,
    question_text: str,
    starter_code: str,
    now: float,
    provider: LLMProvider,
) -> tuple[dict, CheckIn]:
    """Take one Check-in and return the updated watch with it (ADR 0018).

    The Offer goes first: two minutes of silence needs no model to
    interpret. Otherwise the gates (typing-anchored interval, cooldown,
    cap) decide whether this poll becomes an LLM look at all, and both
    cooldowns and provider failures answer silent - a poll never surfaces
    an error.

    Scalars, not the Question: the Watcher stays ignorant of the shape of
    the state it is stored in (ADR 0027).
    """
    if offer_due(watch, now):
        watch = note_check_in(watch, starter_code, now)
        watch = note_interjection(watch, now, action="offer")
        return watch, CheckIn(action="offer", remark=OFFER_REMARK)

    if not check_in_due(watch, now):
        return watch, CheckIn(action="silent", remark="")

    code = watch["code"] if watch["code"] is not None else starter_code
    failure = None
    try:
        decision = await provider.watch_code(
            question=question_text,
            code=code,
            stuck=is_stuck(watch, starter_code),
            seconds_elapsed=now - watch["started_at"],
            runs_summary=describe_runs(watch),
        )
    except ProviderError as exc:
        # A watcher that can't think stays quiet (ADR 0018). The class name
        # is all that leaves this module - never the code, never the
        # chained traceback (Gemini's key rides in its request URL, ADR 0013).
        failure = type(exc).__name__
        decision = WatchDecision(action="silent", remark="")

    # The look is recorded even on failure, so a failing provider is not
    # hammered again on the next poll.
    watch = note_check_in(watch, code, now)
    if decision.action == "silent":
        return watch, CheckIn(action="silent", remark="", failure=failure)

    watch = note_interjection(watch, now, decision.action)
    return watch, CheckIn(action=decision.action, remark=decision.remark)
