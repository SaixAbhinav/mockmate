import pytest

from app.providers import ProviderUnavailableError, ScriptedProvider, WatchDecision
from app.watcher import (
    CHECK_IN_INTERVAL_SECONDS,
    INTERJECTION_COOLDOWN_SECONDS,
    MAX_INTERJECTIONS_PER_QUESTION,
    OFFER_AFTER_SECONDS,
    OFFER_REMARK,
    CheckIn,
    check_in,
    check_in_due,
    describe_runs,
    is_stuck,
    note_chat,
    note_check_in,
    note_interjection,
    note_reply,
    observe_run,
    observe_snapshot,
    offer_due,
    start_watch,
)

pytestmark = pytest.mark.anyio

STARTER = "def f(nums):\n    pass\n"
QUESTION = "Return the running total of a list of numbers."


def test_no_check_in_before_typing_plus_the_interval():
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)

    assert check_in_due(watch, now=1030.0 + CHECK_IN_INTERVAL_SECONDS - 1) is False


def test_check_in_due_after_typing_plus_the_interval():
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)

    assert check_in_due(watch, now=1030.0 + CHECK_IN_INTERVAL_SECONDS) is True


def test_no_llm_look_while_the_candidate_has_never_typed():
    # The Offer owns the never-typed case; the LLM look waits for typing.
    watch = start_watch(now=1000.0)

    assert check_in_due(watch, now=999999.0) is False


def test_typing_started_at_is_stamped_only_once():
    watch = observe_snapshot(start_watch(now=1000.0), "a", now=1030.0)
    watch = observe_snapshot(watch, "ab", now=1060.0)

    assert watch["typing_started_at"] == 1030.0


def test_check_ins_are_spaced_by_the_interval():
    watch = note_check_in(start_watch(now=1000.0), STARTER, now=1100.0)

    assert check_in_due(watch, now=1100.0 + CHECK_IN_INTERVAL_SECONDS - 1) is False
    assert check_in_due(watch, now=1100.0 + CHECK_IN_INTERVAL_SECONDS) is True


def test_speaking_starts_the_longer_cooldown():
    watch = note_check_in(start_watch(now=1000.0), STARTER, now=1100.0)
    watch = note_interjection(watch, now=1100.0, action="ask")

    # 75 s later the look interval has passed, but the 90 s speech cooldown has not.
    assert check_in_due(watch, now=1100.0 + CHECK_IN_INTERVAL_SECONDS) is False
    assert check_in_due(watch, now=1100.0 + INTERJECTION_COOLDOWN_SECONDS) is True


def test_interjection_cap_silences_the_watcher_for_good():
    watch = note_check_in(start_watch(now=1000.0), STARTER, now=1100.0)
    for i in range(MAX_INTERJECTIONS_PER_QUESTION):
        watch = note_interjection(watch, now=1100.0 + i, action="ask")

    assert check_in_due(watch, now=999999.0) is False


def test_offer_due_after_the_grace_when_never_typed():
    watch = start_watch(now=1000.0)

    assert offer_due(watch, now=1000.0 + OFFER_AFTER_SECONDS - 1) is False
    assert offer_due(watch, now=1000.0 + OFFER_AFTER_SECONDS) is True


def test_no_offer_once_typing_has_started():
    watch = observe_snapshot(start_watch(now=1000.0), "x", now=1010.0)

    assert offer_due(watch, now=999999.0) is False


def test_offer_happens_at_most_once():
    watch = note_interjection(start_watch(now=1000.0), now=1120.0, action="offer")

    assert offer_due(watch, now=999999.0) is False


def test_stuck_when_no_snapshot_ever_arrived():
    watch = start_watch(now=1000.0)

    assert is_stuck(watch, starter_code=STARTER) is True


def test_not_stuck_after_a_real_edit():
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "    return nums\n", now=1010.0)

    assert is_stuck(watch, starter_code=STARTER) is False


def test_whitespace_only_changes_still_count_as_stuck():
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "\n\n   ", now=1010.0)

    assert is_stuck(watch, starter_code=STARTER) is True


def test_stuck_is_measured_against_the_last_check_in():
    edited = STARTER + "    return nums\n"
    watch = observe_snapshot(start_watch(now=1000.0), edited, now=1010.0)
    watch = note_check_in(watch, edited, now=1100.0)  # the watcher saw this code

    assert is_stuck(watch, starter_code=STARTER) is True  # nothing new since


def test_note_interjection_counts_hints_but_not_offers_or_asks():
    watch = note_interjection(start_watch(now=1000.0), now=1100.0, action="offer")
    watch = note_interjection(watch, now=1200.0, action="hint")
    watch = note_interjection(watch, now=1300.0, action="ask")

    assert watch["interjections"] == 3
    assert watch["hints"] == 1


def test_observe_run_tracks_the_latest_result():
    watch = observe_run(start_watch(now=1000.0), passed=0, total=4)
    watch = observe_run(watch, passed=2, total=4)

    assert watch["runs"] == 2
    assert (watch["last_passed"], watch["last_total"]) == (2, 4)


def test_note_chat_counts_exchanges():
    watch = note_chat(note_chat(start_watch(now=1000.0)))

    assert watch["chats"] == 2


def test_a_reply_starts_the_interjection_cooldown():
    # The Interviewer has just answered the Candidate, so the Watcher must not
    # follow it seconds later with an unprompted remark (ADR 0028).
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)
    due = 1030.0 + CHECK_IN_INTERVAL_SECONDS
    assert check_in_due(watch, due) is True  # the look would otherwise be due

    watch = note_reply(watch, due)

    assert check_in_due(watch, due + 1.0) is False
    assert check_in_due(watch, due + INTERJECTION_COOLDOWN_SECONDS) is True


def test_a_reply_is_not_an_interjection():
    # The Candidate asked for it, so it costs nothing from the cap that bounds
    # *unprompted* remarks - otherwise a talkative Candidate would spend the
    # Watcher's three interjections without it ever choosing to speak (ADR 0028).
    watch = note_reply(start_watch(now=1000.0), 1010.0)

    assert (watch["interjections"], watch["hints"]) == (0, 0)


def test_describe_runs_reads_naturally():
    watch = start_watch(now=1000.0)
    assert "not run" in describe_runs(watch)

    watch = observe_run(watch, passed=2, total=4)
    summary = describe_runs(watch)
    assert "1" in summary
    assert "2 of 4" in summary


# --- The policy itself: one Check-in end to end (ADR 0027) ---


class _SpeakingWatcher(ScriptedProvider):
    """Provider that always wants to speak, so the gates are the only thing
    deciding whether it is asked at all."""

    def __init__(self, action="hint", remark="Try a running total."):
        self.decision = WatchDecision(action=action, remark=remark)
        self.calls = 0
        self.last_code = None
        self.last_stuck = None

    async def watch_code(self, question, code, stuck, seconds_elapsed, runs_summary):
        self.calls += 1
        self.last_code = code
        self.last_stuck = stuck
        return self.decision


class _FailingWatcher(ScriptedProvider):
    """Provider that cannot answer the look at all (ADR 0013)."""

    async def watch_code(self, question, code, stuck, seconds_elapsed, runs_summary):
        raise ProviderUnavailableError("rate limited")


async def _look(watch, now, provider):
    return await check_in(
        watch,
        question_text=QUESTION,
        starter_code=STARTER,
        now=now,
        provider=provider,
    )


async def test_a_poll_that_is_not_due_returns_the_watch_untouched():
    watch = start_watch(now=1000.0)
    provider = _SpeakingWatcher()

    returned, decision = await _look(watch, now=1005.0, provider=provider)

    assert decision == CheckIn(action="silent", remark="")
    assert returned == watch  # the caller still has a fresh watch to persist
    assert provider.calls == 0


async def test_the_offer_beats_a_due_llm_look():
    # The Candidate has never typed but a look is due anyway (an earlier look
    # was recorded). The deterministic Offer is ordered first (ADR 0018).
    watch = note_check_in(start_watch(now=1000.0), STARTER, now=1010.0)
    now = 1000.0 + OFFER_AFTER_SECONDS
    assert check_in_due(watch, now) is True  # both gates are open
    provider = _SpeakingWatcher()

    watch, decision = await _look(watch, now=now, provider=provider)

    assert decision == CheckIn(action="offer", remark=OFFER_REMARK)
    assert provider.calls == 0  # deterministic - no LLM involved
    assert (watch["interjections"], watch["hints"]) == (1, 0)
    # The Offer counts as a look too, or the interval never restarts and the
    # next poll takes an LLM look the moment the cooldown lifts (ADR 0018).
    assert (watch["last_check_at"], watch["last_checked_code"]) == (now, STARTER)


async def test_the_look_is_handed_the_latest_snapshot():
    edited = STARTER + "    return nums\n"
    watch = observe_snapshot(start_watch(now=1000.0), edited, now=1030.0)
    provider = _SpeakingWatcher()

    await _look(watch, now=1030.0 + CHECK_IN_INTERVAL_SECONDS, provider=provider)

    assert provider.last_code == edited
    assert provider.last_stuck is False  # they edited since the starter


async def test_a_hint_is_counted_as_a_hint():
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)
    now = 1030.0 + CHECK_IN_INTERVAL_SECONDS

    watch, decision = await _look(watch, now=now, provider=_SpeakingWatcher(action="hint"))

    assert decision == CheckIn(action="hint", remark="Try a running total.")
    assert (watch["interjections"], watch["hints"]) == (1, 1)
    assert watch["last_spoke_at"] == now


async def test_an_ask_is_an_interjection_but_not_a_hint():
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)
    provider = _SpeakingWatcher(action="ask", remark="What's your plan here?")

    watch, decision = await _look(
        watch, now=1030.0 + CHECK_IN_INTERVAL_SECONDS, provider=provider
    )

    assert decision.action == "ask"
    assert (watch["interjections"], watch["hints"]) == (1, 0)


async def test_a_due_look_that_stays_silent_is_still_recorded():
    typed = STARTER + "x"
    watch = observe_snapshot(start_watch(now=1000.0), typed, now=1030.0)
    now = 1030.0 + CHECK_IN_INTERVAL_SECONDS

    # The scripted provider never interrupts.
    watch, decision = await _look(watch, now=now, provider=ScriptedProvider())

    assert decision == CheckIn(action="silent", remark="")
    assert watch["last_check_at"] == now
    assert watch["last_checked_code"] == typed
    assert watch["interjections"] == 0
    assert watch["last_spoke_at"] is None  # silence starts no cooldown


async def test_a_provider_failure_answers_silent():
    watch = observe_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)

    watch, decision = await _look(
        watch, now=1030.0 + CHECK_IN_INTERVAL_SECONDS, provider=_FailingWatcher()
    )

    # Silent to the Candidate, but the failure is reported so the endpoint can
    # log it against the Session - a closed gate reports nothing (ADR 0027).
    assert decision == CheckIn(
        action="silent", remark="", failure="ProviderUnavailableError"
    )
    assert watch["interjections"] == 0


async def test_the_look_is_recorded_even_when_the_provider_failed():
    # Otherwise a failing provider is hammered again on the next poll (ADR 0018).
    typed = STARTER + "x"
    watch = observe_snapshot(start_watch(now=1000.0), typed, now=1030.0)
    now = 1030.0 + CHECK_IN_INTERVAL_SECONDS

    watch, _ = await _look(watch, now=now, provider=_FailingWatcher())

    assert watch["last_check_at"] == now
    assert watch["last_checked_code"] == typed
    assert check_in_due(watch, now) is False
