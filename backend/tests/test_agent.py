import pytest

from app.agent import build_graph, start_session, submit_answer
from app.providers import Judgment, ProviderError, ScriptedProvider

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
    provider = FakeProvider([ProviderError("boom")])
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
