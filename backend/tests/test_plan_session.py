from app.questions import DIFFICULTIES, plan_session


def test_plan_session_draws_between_six_and_eight_questions():
    queue = plan_session("ml_genai", seed=1)
    assert 6 <= len(queue) <= 8


def test_plan_session_has_no_duplicate_questions():
    queue = plan_session("ml_genai", seed=1)
    assert len(set(q.question for q in queue)) == len(queue)


def test_plan_session_sorted_easy_to_hard():
    queue = plan_session("ml_genai", seed=1)
    indices = [DIFFICULTIES.index(q.difficulty) for q in queue]
    assert indices == sorted(indices)


def test_plan_session_deterministic_under_same_seed():
    first = plan_session("ml_genai", seed=42)
    second = plan_session("ml_genai", seed=42)
    assert [q.question for q in first] == [q.question for q in second]
