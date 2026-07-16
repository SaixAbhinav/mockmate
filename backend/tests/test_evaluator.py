import pytest

from app.evaluator import aggregate_scores, build_evaluator_graph, evaluate_session
from app.providers import (
    AnswerScore,
    Assessment,
    ProviderMalformedError,
    ProviderUnavailableError,
)

pytestmark = pytest.mark.anyio


def make_record(question, answered=True, answers=None):
    return {
        "question": question,
        "topic": "t",
        "difficulty": "easy",
        "follow_up_hints": ["hint"],
        "answers": answers if answers is not None else ["an answer"],
        "answered": answered,
    }


class FakeEvaluator:
    """Scores by lookup; records which questions it was asked to score."""

    name = "fake"

    def __init__(self, scores=None, assessment=None):
        self._scores = scores or {}
        self._assessment = assessment or Assessment("Overall.", ["s"], ["i"])
        self.scored_questions = []
        self.assess_calls = 0

    async def evaluate_answer(self, question, follow_up_hints, answers):
        self.scored_questions.append(question)
        result = self._scores.get(question, AnswerScore(3, 3, 3, "fine"))
        if isinstance(result, Exception):
            raise result
        return result

    async def assess_session(self, scores):
        self.assess_calls += 1
        if isinstance(self._assessment, Exception):
            raise self._assessment
        return self._assessment


async def test_scores_every_answered_question_once():
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [make_record("Q1"), make_record("Q2"), make_record("Q3")]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert sorted(provider.scored_questions) == ["Q1", "Q2", "Q3"]
    assert len(evaluation["questions"]) == 3
    assert provider.assess_calls == 1


async def test_questions_are_returned_in_interview_order():
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [make_record("Q1"), make_record("Q2"), make_record("Q3")]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert [q["question"] for q in evaluation["questions"]] == ["Q1", "Q2", "Q3"]


async def test_unanswered_questions_are_skipped_not_scored():
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [make_record("Q1"), make_record("Q2", answered=False)]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert provider.scored_questions == ["Q1"]  # no LLM call for the unanswered one
    skipped = next(q for q in evaluation["questions"] if q["question"] == "Q2")
    assert skipped["skipped"] is True


async def test_averages_exclude_skipped_questions():
    provider = FakeEvaluator(scores={"Q1": AnswerScore(5, 5, 5, "great")})
    graph = build_evaluator_graph(provider)
    completed = [make_record("Q1"), make_record("Q2", answered=False)]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert evaluation["averages"] == {"correctness": 5.0, "depth": 5.0, "clarity": 5.0}


async def test_coverage_reports_answered_out_of_total():
    # Disengaging must show up as low Coverage rather than a flattering average.
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [
        make_record("Q1"),
        make_record("Q2", answered=False),
        make_record("Q3", answered=False),
    ]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert evaluation["coverage"] == {"answered": 1, "total": 3}


async def test_malformed_score_marks_one_question_unscored_without_sinking_evaluation():
    provider = FakeEvaluator(
        scores={"Q1": AnswerScore(4, 4, 4, "ok"), "Q2": ProviderMalformedError("boom")}
    )
    graph = build_evaluator_graph(provider)
    completed = [make_record("Q1"), make_record("Q2")]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    unscored = next(q for q in evaluation["questions"] if q["question"] == "Q2")
    assert unscored["unscored"] is True
    assert evaluation["averages"] == {"correctness": 4.0, "depth": 4.0, "clarity": 4.0}
    assert evaluation["assessment"]


async def test_unavailable_provider_marks_question_unscored():
    # A rate-limited Score costs one question, not the whole Evaluation (ADR 0013).
    provider = FakeEvaluator(
        scores={"Q1": AnswerScore(4, 4, 4, "ok"), "Q2": ProviderUnavailableError("429")}
    )
    graph = build_evaluator_graph(provider)
    completed = [make_record("Q1"), make_record("Q2")]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    unscored = next(q for q in evaluation["questions"] if q["question"] == "Q2")
    assert unscored["unscored"] is True


async def test_malformed_assessment_falls_back_without_crashing():
    provider = FakeEvaluator(assessment=ProviderMalformedError("bad"))
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_record("Q1")])

    assert evaluation["assessment"]
    assert evaluation["strengths"] == []
    assert evaluation["improvements"] == []


async def test_averages_are_none_when_nothing_was_scored():
    assert aggregate_scores([{"question": "Q", "skipped": True}]) == {
        "correctness": None,
        "depth": None,
        "clarity": None,
    }


async def test_retryable_failure_flag_set_when_score_unavailable():
    provider = FakeEvaluator(scores={"Q1": ProviderUnavailableError("429")})
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_record("Q1")])

    assert evaluation["retryable_failure"] is True


async def test_retryable_failure_flag_not_set_when_score_malformed():
    provider = FakeEvaluator(scores={"Q1": ProviderMalformedError("bad json")})
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_record("Q1")])

    assert evaluation["retryable_failure"] is False


async def test_retryable_failure_flag_set_when_assessment_unavailable():
    provider = FakeEvaluator(assessment=ProviderUnavailableError("429"))
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_record("Q1")])

    assert evaluation["retryable_failure"] is True


async def test_retryable_key_absent_from_per_question_output():
    provider = FakeEvaluator(scores={"Q1": ProviderUnavailableError("429")})
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_record("Q1")])

    assert "retryable" not in evaluation["questions"][0]


async def test_intro_is_excluded_from_the_evaluation():
    # Scoring "tell me about yourself" on correctness is meaningless, and a
    # freebie in Coverage would flatter every Session (ADR 0015).
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [
        {**make_record("Tell me about yourself"), "stage": "intro"},
        {**make_record("Q1"), "stage": "warm_up"},
    ]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert [q["question"] for q in evaluation["questions"]] == ["Q1"]
    assert evaluation["coverage"] == {"answered": 1, "total": 1}
    assert provider.scored_questions == ["Q1"]
