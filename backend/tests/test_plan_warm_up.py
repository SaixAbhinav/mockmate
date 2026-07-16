from app.questions import DIFFICULTIES, plan_warm_up


def test_plan_warm_up_draws_three_questions():
    assert len(plan_warm_up("ml_genai", seed=1)) == 3


def test_plan_warm_up_has_no_duplicate_questions():
    queue = plan_warm_up("ml_genai", seed=1)
    assert len(set(q.question for q in queue)) == len(queue)


def test_plan_warm_up_sorted_easy_to_hard():
    indices = [DIFFICULTIES.index(q.difficulty) for q in plan_warm_up("ml_genai", seed=1)]
    assert indices == sorted(indices)


def test_plan_warm_up_deterministic_under_same_seed():
    assert [q.question for q in plan_warm_up("ml_genai", seed=42)] == [
        q.question for q in plan_warm_up("ml_genai", seed=42)
    ]
