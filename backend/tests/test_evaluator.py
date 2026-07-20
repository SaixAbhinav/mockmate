import pytest

from app.evaluator import (
    aggregate_scores,
    aggregate_submission_scores,
    build_evaluator_graph,
    evaluate_session,
)
from app.providers import (
    AnswerScore,
    Assessment,
    ProviderMalformedError,
    ProviderUnavailableError,
    SubmissionScore,
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


def make_dsa_record(
    question="Implement running_sum",
    passed=3,
    total=4,
    status="ok",
    hints=0,
    runs=0,
    answers=None,
    submission=True,
):
    record = {
        "question": question,
        "topic": "arrays",
        "difficulty": "easy",
        "stage": "dsa",
        "follow_up_hints": [],
        "answers": answers if answers is not None else ["I used a running total."],
        "answered": True,
    }
    if submission:
        record["submission"] = {
            "code": "def f(nums):\n    return sum(nums)\n",
            "status": status,
            "passed": passed,
            "total": total,
        }
    if hints or runs:
        record["watch"] = {"interjections": hints, "hints": hints, "chats": 0, "runs": runs}
    return record


class FakeEvaluator:
    """Scores by lookup; records which questions it was asked to score."""

    name = "fake"

    def __init__(self, scores=None, assessment=None, submission_scores=None):
        self._scores = scores or {}
        self._assessment = assessment or Assessment("Overall.", ["s"], ["i"])
        self._submission_scores = submission_scores or {}
        self.scored_questions = []
        self.submission_calls = []
        self.assess_calls = 0
        self.assess_scores = None

    async def evaluate_answer(self, question, follow_up_hints, answers):
        self.scored_questions.append(question)
        result = self._scores.get(question, AnswerScore(3, 3, 3, "fine"))
        if isinstance(result, Exception):
            raise result
        return result

    async def evaluate_submission(
        self, question, code, results_summary, discussion, hints_used, runs
    ):
        self.submission_calls.append(
            {
                "question": question,
                "results_summary": results_summary,
                "hints_used": hints_used,
                "runs": runs,
            }
        )
        result = self._submission_scores.get(question, SubmissionScore(3, 3, "fine code"))
        if isinstance(result, Exception):
            raise result
        return result

    async def assess_session(self, scores):
        self.assess_calls += 1
        self.assess_scores = scores
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


async def test_dsa_question_is_scored_into_its_own_section():
    # Replaces test_dsa_round_is_excluded_from_the_evaluation: ADR 0020 is the
    # "future day" that test was holding the door for. DSA questions still
    # never enter the spoken questions, averages, or Coverage.
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [
        {**make_record("Tell me about yourself"), "stage": "intro"},
        {**make_record("Q1"), "stage": "warm_up"},
        make_dsa_record("Implement running_sum"),
    ]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert [q["question"] for q in evaluation["questions"]] == ["Q1"]
    assert evaluation["coverage"] == {"answered": 1, "total": 1}
    dsa = evaluation["dsa"]["questions"]
    assert [q["question"] for q in dsa] == ["Implement running_sum"]
    assert dsa[0]["tests"] == {"status": "ok", "passed": 3, "total": 4}
    assert (dsa[0]["code_quality"], dsa[0]["approach"]) == (3, 3)
    assert provider.assess_calls == 1  # both fan-outs share one assess join


async def test_dsa_correctness_comes_from_the_tests_not_the_model():
    provider = FakeEvaluator(
        submission_scores={"Q": SubmissionScore(5, 5, "beautiful code, shame it fails")}
    )
    graph = build_evaluator_graph(provider)
    completed = [make_dsa_record("Q", passed=0, total=4)]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    entry = evaluation["dsa"]["questions"][0]
    assert entry["tests"]["passed"] == 0  # the model cannot overrule the Runner
    assert "correctness" not in entry


async def test_watch_counts_reach_the_provider_and_the_payload():
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [make_dsa_record("Q", hints=2, runs=5)]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    call = provider.submission_calls[0]
    assert (call["hints_used"], call["runs"]) == (2, 5)
    entry = evaluation["dsa"]["questions"][0]
    assert (entry["hints"], entry["runs"]) == (2, 5)


async def test_dsa_record_without_a_watch_defaults_to_zero_counts():
    # A Candidate who types immediately and never triggers a Check-in produces
    # a record with no watch key at all.
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_dsa_record("Q")])

    entry = evaluation["dsa"]["questions"][0]
    assert (entry["hints"], entry["runs"]) == (0, 0)


async def test_failed_submission_score_keeps_the_test_facts():
    provider = FakeEvaluator(submission_scores={"Q": ProviderMalformedError("bad")})
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_dsa_record("Q")])

    entry = evaluation["dsa"]["questions"][0]
    assert entry["unscored"] is True
    assert entry["tests"] == {"status": "ok", "passed": 3, "total": 4}
    assert evaluation["retryable_failure"] is False


async def test_unavailable_submission_score_sets_the_retryable_flag():
    provider = FakeEvaluator(submission_scores={"Q": ProviderUnavailableError("429")})
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(graph, "s1", "ml_genai", [make_dsa_record("Q")])

    assert evaluation["retryable_failure"] is True
    assert "retryable" not in evaluation["dsa"]["questions"][0]


async def test_dsa_averages_and_total_hints():
    provider = FakeEvaluator(
        submission_scores={
            "Q1": SubmissionScore(4, 2, "a"),
            "Q2": SubmissionScore(2, 4, "b"),
        }
    )
    graph = build_evaluator_graph(provider)
    completed = [make_dsa_record("Q1", hints=1), make_dsa_record("Q2", hints=2)]

    evaluation = await evaluate_session(graph, "s1", "ml_genai", completed)

    assert evaluation["dsa"]["averages"] == {"code_quality": 3.0, "approach": 3.0}
    assert evaluation["dsa"]["hints_used"] == 3


async def test_dsa_record_without_a_submission_is_skipped_not_scored():
    # Defensive: the Submission is the only way past a coding question, so this
    # record should be impossible - but nothing to score must mean no LLM call.
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)

    evaluation = await evaluate_session(
        graph, "s1", "ml_genai", [make_dsa_record("Q", submission=False)]
    )

    assert provider.submission_calls == []
    entry = evaluation["dsa"]["questions"][0]
    assert entry["skipped"] is True
    assert "tests" not in entry


async def test_assessment_input_includes_the_coding_round():
    provider = FakeEvaluator()
    graph = build_evaluator_graph(provider)
    completed = [make_record("Q1"), make_dsa_record("Q2")]

    await evaluate_session(graph, "s1", "ml_genai", completed)

    assert any(s.get("kind") == "dsa" for s in provider.assess_scores)
