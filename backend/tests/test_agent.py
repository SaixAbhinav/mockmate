import pytest

from app.agent import build_graph, start_session, submit_answer, submit_code
from app.providers import (
    Judgment,
    ProviderMalformedError,
    ProviderUnavailableError,
    ScriptedProvider,
)
from app.runner import RunResult, TestCaseResult

pytestmark = pytest.mark.anyio


class FakeProvider:
    """Returns a scripted sequence of judgments/errors, one per call."""

    name = "fake"

    def __init__(self, judgments, wrap_up_text="Nice work today."):
        self._judgments = list(judgments)
        self._wrap_up_text = wrap_up_text
        self.calls = 0

    async def judge_answer(self, question, follow_up_hints, history, answer):
        j = self._judgments[min(self.calls, len(self._judgments) - 1)]
        self.calls += 1
        if isinstance(j, Exception):
            raise j
        return j

    async def wrap_up(self, transcript):
        return self._wrap_up_text


async def test_full_run_with_scripted_provider_reaches_wrap_up_no_repeats():
    provider = ScriptedProvider()
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    asked = [state["current_question"]["question"]]

    for _ in range(50):
        if state["phase"] == "done":
            break
        state = await submit_answer(graph, state, "some answer")
        if state["phase"] == "asking":
            asked.append(state["current_question"]["question"])

    assert state["phase"] == "done"
    assert len(asked) == len(set(asked))


async def test_probe_triggers_on_shallow_answer_same_question():
    provider = FakeProvider([Judgment("probe", "Can you elaborate?", False)])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    first_question = state["current_question"]

    result = await submit_answer(graph, state, "shallow answer")

    assert result["phase"] == "probing"
    assert result["follow_up_count"] == 1
    assert result["current_question"] == first_question
    assert result["reply"] == "Can you elaborate?"


async def test_clarify_triggers_on_offtopic_answer_same_question():
    provider = FakeProvider([Judgment("clarify", "Could you clarify?", False)])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    first_question = state["current_question"]

    result = await submit_answer(graph, state, "unrelated answer")

    assert result["phase"] == "clarifying"
    assert result["follow_up_count"] == 1
    assert result["current_question"] == first_question


async def test_shared_probe_clarify_budget_caps_at_two_combined():
    provider = FakeProvider(
        [
            Judgment("probe", "r1", False),
            Judgment("clarify", "r2", False),
            Judgment("probe", "r3", False),  # 3rd follow-up attempt: budget exhausted
        ]
    )
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    first_question = state["current_question"]

    state = await submit_answer(graph, state, "a1")
    assert state["phase"] == "probing" and state["follow_up_count"] == 1

    state = await submit_answer(graph, state, "a2")
    assert state["phase"] == "clarifying" and state["follow_up_count"] == 2

    state = await submit_answer(graph, state, "a3")

    assert state["phase"] in ("asking", "done")
    assert state["current_question"] != first_question or state["phase"] == "done"


async def test_answered_false_when_budget_exhausted_unresolved():
    provider = FakeProvider(
        [
            Judgment("clarify", "r1", False),
            Judgment("clarify", "r2", False),
            Judgment("clarify", "r3", False),
        ]
    )
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    first_question = state["current_question"]["question"]

    state = await submit_answer(graph, state, "a1")
    state = await submit_answer(graph, state, "a2")
    state = await submit_answer(graph, state, "a3")

    record = next(c for c in state["completed"] if c["question"] == first_question)
    assert record["answered"] is False


async def test_forced_advance_does_not_speak_the_dangling_follow_up():
    provider = FakeProvider(
        [
            Judgment("probe", "r1", False),
            Judgment("probe", "r2", False),
            Judgment("probe", "Tell me more about X?", False),
        ]
    )
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)

    state = await submit_answer(graph, state, "a1")
    state = await submit_answer(graph, state, "a2")
    state = await submit_answer(graph, state, "a3")

    # Budget exhausted: the judge's follow-up must be discarded, not spoken.
    assert "Tell me more about X?" not in state["reply"]
    if state["phase"] == "asking":
        assert state["current_question"]["question"] in state["reply"]


async def test_answered_true_when_probe_budget_exhausts():
    provider = FakeProvider(
        [
            Judgment("probe", "r1", False),
            Judgment("probe", "r2", False),
            Judgment("probe", "r3", False),
        ]
    )
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    first_question = state["current_question"]["question"]

    state = await submit_answer(graph, state, "a1")
    state = await submit_answer(graph, state, "a2")
    state = await submit_answer(graph, state, "a3")

    # Probe exhaustion = shallow but answered (ADR 0006); only Clarify
    # exhaustion marks answered: false.
    record = next(c for c in state["completed"] if c["question"] == first_question)
    assert record["answered"] is True


async def test_malformed_judgment_defaults_to_advance_without_crashing():
    provider = FakeProvider([ProviderMalformedError("boom")])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)

    result = await submit_answer(graph, state, "answer")

    assert result["phase"] in ("asking", "done")
    assert result["classification"] == "advance"


async def test_unknown_classification_defaults_to_advance():
    provider = FakeProvider([Judgment("mystery", "huh", True)])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)

    result = await submit_answer(graph, state, "answer")

    assert result["classification"] == "advance"


async def test_unavailable_provider_propagates_and_does_not_advance():
    # A transient 429 must not silently burn the Candidate's question (ADR 0013).
    provider = FakeProvider([ProviderUnavailableError("rate limited")])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    first_question = state["current_question"]

    with pytest.raises(ProviderUnavailableError):
        await submit_answer(graph, state, "my answer")

    assert state["current_question"] == first_question  # caller's state untouched


async def test_completed_record_carries_question_metadata_and_answers():
    provider = FakeProvider([Judgment("advance", "ok", True)])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)
    first = state["current_question"]

    state = await submit_answer(graph, state, "my answer")

    record = state["completed"][0]
    assert record["question"] == first["question"]
    assert record["topic"] == first["topic"]
    assert record["difficulty"] == first["difficulty"]
    assert record["follow_up_hints"] == first["follow_up_hints"]
    assert record["answers"] == ["my answer"]
    assert record["answered"] is True


async def test_completed_record_collects_every_answer_for_a_probed_question():
    provider = FakeProvider(
        [
            Judgment("probe", "Say more?", False),
            Judgment("advance", "Good.", True),
        ]
    )
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)

    state = await submit_answer(graph, state, "shallow")
    state = await submit_answer(graph, state, "deeper")

    assert state["completed"][0]["answers"] == ["shallow", "deeper"]


async def test_answers_do_not_leak_between_questions():
    provider = FakeProvider([Judgment("advance", "ok", True)])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)

    state = await submit_answer(graph, state, "a1")
    state = await submit_answer(graph, state, "a2")

    assert state["completed"][0]["answers"] == ["a1"]
    assert state["completed"][1]["answers"] == ["a2"]


async def test_intro_question_is_asked_first():
    state = start_session("s1", "ml_genai", seed=1)

    assert state["current_question"]["stage"] == "intro"
    assert "tell me about yourself" in state["current_question"]["question"].lower()


async def test_generated_warm_up_questions_fill_the_queue():
    generated = [
        {"topic": "projects", "difficulty": "easy", "question": "GQ1", "follow_up_hints": ["h"]},
        {"topic": "skills", "difficulty": "medium", "question": "GQ2", "follow_up_hints": ["h"]},
    ]

    state = start_session("s1", "ml_genai", seed=1, warm_up_questions=generated)

    assert len(state["queue"]) == 4  # 2 generated warm-ups + 2 DSA (ADR 0012)
    assert [q["question"] for q in state["queue"][:2]] == ["GQ1", "GQ2"]
    assert all(q["stage"] == "warm_up" for q in state["queue"][:2])
    assert all(q["domain"] == "ml_genai" for q in state["queue"][:2])
    assert [q["stage"] for q in state["queue"][-2:]] == ["dsa", "dsa"]


async def test_curated_fallback_fills_the_queue_when_no_generated_questions():
    state = start_session("s1", "ml_genai", seed=1)

    assert len(state["queue"]) == 5  # 3 curated warm-ups + 2 DSA (ADR 0012)
    assert all(q["stage"] == "warm_up" for q in state["queue"][:3])


async def test_completed_records_carry_stage():
    provider = FakeProvider([Judgment("advance", "ok", True)])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)

    state = await submit_answer(graph, state, "about me")

    assert state["completed"][0]["stage"] == "intro"


async def test_session_wraps_after_the_dsa_round():
    provider = FakeProvider([Judgment("advance", "ok", True)])
    graph = build_graph(provider)
    state = start_session("s1", "ml_genai", seed=1)

    answers = 0
    while state["phase"] != "done":
        state = await submit_answer(graph, state, "answer")
        answers += 1

    assert answers == 6  # intro + 3 warm-up + 2 DSA (ADR 0012)


def _fast_forward_to_dsa(state):
    """Make the last queued (DSA) question current, with an empty queue."""
    dsa_question = state["queue"][-1]
    return {**state, "current_question": dsa_question, "queue": []}


async def test_queue_ends_with_two_dsa_questions():
    state = start_session("s1", "ml_genai", seed=1)

    dsa_entries = [q for q in state["queue"] if q["stage"] == "dsa"]
    assert len(state["queue"]) == 5  # 3 warm-up + 2 DSA (ADR 0012)
    assert [q["stage"] for q in state["queue"][-2:]] == ["dsa", "dsa"]
    assert dsa_entries[0]["difficulty"] == "easy"
    for q in dsa_entries:
        assert q["function_name"] and q["starter_code"] and q["test_cases"]


async def test_submit_code_attaches_submission_and_opens_discussion():
    state = _fast_forward_to_dsa(start_session("s1", "ml_genai", seed=1))
    run_result = RunResult(
        status="ok",
        error=None,
        results=[TestCaseResult(args=[1], expected=1, got="1", passed=True)],
    )

    state = submit_code(state, "def f(x):\n    return x\n", run_result, "Nice. Why this way?")

    submission = state["current_question"]["submission"]
    assert submission["code"].startswith("def f")
    assert submission["status"] == "ok"
    assert (submission["passed"], submission["total"]) == (1, 1)
    assert state["phase"] == "probing"
    assert state["reply"] == "Nice. Why this way?"
    assert state["transcript"][-1] == {"role": "assistant", "content": "Nice. Why this way?"}
    assert "def f" in state["transcript"][-2]["content"]


async def test_completed_record_carries_the_submission():
    provider = FakeProvider([Judgment("advance", "ok", True)])
    graph = build_graph(provider)
    state = _fast_forward_to_dsa(start_session("s1", "ml_genai", seed=1))
    run_result = RunResult(status="ok", error=None, results=[])
    state = submit_code(state, "code", run_result, "reaction")

    state = await submit_answer(graph, state, "I used a running total.")

    assert state["phase"] == "done"  # queue was empty, so the Session wraps
    assert state["completed"][-1]["submission"]["code"] == "code"
    assert "submission" not in state["completed"][0] if len(state["completed"]) > 1 else True
