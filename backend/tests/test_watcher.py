from app.watcher import (
    CHECK_IN_INTERVAL_SECONDS,
    INTERJECTION_COOLDOWN_SECONDS,
    MAX_INTERJECTIONS_PER_QUESTION,
    OFFER_AFTER_SECONDS,
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

STARTER = "def f(nums):\n    pass\n"


def test_no_check_in_before_typing_plus_the_interval():
    watch = record_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)

    assert check_in_due(watch, now=1030.0 + CHECK_IN_INTERVAL_SECONDS - 1) is False


def test_check_in_due_after_typing_plus_the_interval():
    watch = record_snapshot(start_watch(now=1000.0), STARTER + "x", now=1030.0)

    assert check_in_due(watch, now=1030.0 + CHECK_IN_INTERVAL_SECONDS) is True


def test_no_llm_look_while_the_candidate_has_never_typed():
    # The Offer owns the never-typed case; the LLM look waits for typing.
    watch = start_watch(now=1000.0)

    assert check_in_due(watch, now=999999.0) is False


def test_typing_started_at_is_stamped_only_once():
    watch = record_snapshot(start_watch(now=1000.0), "a", now=1030.0)
    watch = record_snapshot(watch, "ab", now=1060.0)

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
    watch = record_snapshot(start_watch(now=1000.0), "x", now=1010.0)

    assert offer_due(watch, now=999999.0) is False


def test_offer_happens_at_most_once():
    watch = note_interjection(start_watch(now=1000.0), now=1120.0, action="offer")

    assert offer_due(watch, now=999999.0) is False


def test_stuck_when_no_snapshot_ever_arrived():
    watch = start_watch(now=1000.0)

    assert is_stuck(watch, starter_code=STARTER) is True


def test_not_stuck_after_a_real_edit():
    watch = record_snapshot(start_watch(now=1000.0), STARTER + "    return nums\n", now=1010.0)

    assert is_stuck(watch, starter_code=STARTER) is False


def test_whitespace_only_changes_still_count_as_stuck():
    watch = record_snapshot(start_watch(now=1000.0), STARTER + "\n\n   ", now=1010.0)

    assert is_stuck(watch, starter_code=STARTER) is True


def test_stuck_is_measured_against_the_last_check_in():
    edited = STARTER + "    return nums\n"
    watch = record_snapshot(start_watch(now=1000.0), edited, now=1010.0)
    watch = note_check_in(watch, edited, now=1100.0)  # the watcher saw this code

    assert is_stuck(watch, starter_code=STARTER) is True  # nothing new since


def test_note_interjection_counts_hints_but_not_offers_or_asks():
    watch = note_interjection(start_watch(now=1000.0), now=1100.0, action="offer")
    watch = note_interjection(watch, now=1200.0, action="hint")
    watch = note_interjection(watch, now=1300.0, action="ask")

    assert watch["interjections"] == 3
    assert watch["hints"] == 1


def test_note_run_tracks_the_latest_result():
    watch = note_run(start_watch(now=1000.0), passed=0, total=4)
    watch = note_run(watch, passed=2, total=4)

    assert watch["runs"] == 2
    assert (watch["last_passed"], watch["last_total"]) == (2, 4)


def test_note_chat_counts_exchanges():
    watch = note_chat(note_chat(start_watch(now=1000.0)))

    assert watch["chats"] == 2


def test_describe_runs_reads_naturally():
    watch = start_watch(now=1000.0)
    assert "not run" in describe_runs(watch)

    watch = note_run(watch, passed=2, total=4)
    summary = describe_runs(watch)
    assert "1" in summary
    assert "2 of 4" in summary
