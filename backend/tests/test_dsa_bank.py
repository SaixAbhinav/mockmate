import pytest
import yaml

from app.questions import QuestionBankError, load_dsa_bank, plan_dsa


def valid_entry(**overrides):
    entry = {
        "domain": "dsa",
        "topic": "arrays",
        "difficulty": "easy",
        "question": "Implement running_sum.",
        "follow_up_hints": ["Ask about complexity"],
        "function_name": "running_sum",
        "signature": "def running_sum(nums: list[int]) -> list[int]:",
        "starter_code": "def running_sum(nums):\n    pass\n",
        "test_cases": [{"args": [[1, 2, 3]], "expected": [1, 3, 6]}],
    }
    entry.update(overrides)
    return entry


def write_bank(tmp_path, entries):
    (tmp_path / "dsa.yaml").write_text(yaml.safe_dump(entries), encoding="utf-8")
    return tmp_path


def test_shipped_dsa_bank_loads_and_validates():
    bank = load_dsa_bank()

    assert len(bank) >= 4
    assert any(q.difficulty == "easy" for q in bank)
    assert any(q.difficulty in ("medium", "hard") for q in bank)


def test_missing_function_name_is_rejected(tmp_path):
    entry = valid_entry()
    del entry["function_name"]

    with pytest.raises(QuestionBankError):
        load_dsa_bank(questions_dir=write_bank(tmp_path, [entry]))


def test_non_identifier_function_name_is_rejected(tmp_path):
    bank_dir = write_bank(tmp_path, [valid_entry(function_name="not valid!")])

    with pytest.raises(QuestionBankError):
        load_dsa_bank(questions_dir=bank_dir)


def test_empty_test_cases_are_rejected(tmp_path):
    bank_dir = write_bank(tmp_path, [valid_entry(test_cases=[])])

    with pytest.raises(QuestionBankError):
        load_dsa_bank(questions_dir=bank_dir)


def test_test_case_without_expected_is_rejected(tmp_path):
    bank_dir = write_bank(tmp_path, [valid_entry(test_cases=[{"args": [1]}])])

    with pytest.raises(QuestionBankError):
        load_dsa_bank(questions_dir=bank_dir)


def test_plan_dsa_draws_one_easy_then_one_harder():
    drawn = plan_dsa(seed=1)

    assert len(drawn) == 2
    assert drawn[0].difficulty == "easy"
    assert drawn[1].difficulty in ("medium", "hard")


def test_plan_dsa_deterministic_under_same_seed():
    assert [q.question for q in plan_dsa(seed=42)] == [
        q.question for q in plan_dsa(seed=42)
    ]
