"""Tests for the offline generation gates (ADR 0024).

The gates decide, by machine, whether a generated candidate question is fit for
a human reviewer to even look at. Coding candidates carry a reference_solution
that the correctness gate runs and then discards.
"""

from scripts.gates import (
    check_correctness,
    check_duplicate,
    check_length,
    check_schema,
    check_warm_up_schema,
    gate_batch,
    gate_candidate,
    gate_warm_up_candidate,
)


def _dsa_candidate(**overrides):
    """A minimal, valid DSA candidate dict; override any field per test."""
    candidate = {
        "domain": "dsa",
        "topic": "arrays",
        "difficulty": "easy",
        "question": (
            "Implement double_all: given a list of integers, return a new list "
            "with every value doubled."
        ),
        "follow_up_hints": ["Ask about the time complexity"],
        "function_name": "double_all",
        "signature": "def double_all(nums: list[int]) -> list[int]:",
        "starter_code": "def double_all(nums):\n    pass\n",
        "test_cases": [
            {"args": [[1, 2, 3]], "expected": [2, 4, 6]},
            {"args": [[]], "expected": []},
        ],
        "reference_solution": "def double_all(nums):\n    return [n * 2 for n in nums]\n",
    }
    candidate.update(overrides)
    return candidate


def test_check_length_accepts_a_short_question():
    assert check_length(_dsa_candidate()).passed


def test_check_length_rejects_an_over_long_question():
    long_question = " ".join(["word"] * 80)
    result = check_length(_dsa_candidate(question=long_question), max_words=50)
    assert not result.passed
    assert "50" in result.reason


def test_check_schema_accepts_a_valid_candidate():
    assert check_schema(_dsa_candidate()).passed


def test_check_schema_accepts_despite_the_reference_solution_field():
    # reference_solution is not part of the bank schema; its presence must not
    # make an otherwise-valid candidate fail (it is stripped before the bank).
    assert check_schema(_dsa_candidate()).passed


def test_check_schema_rejects_a_missing_required_field():
    candidate = _dsa_candidate()
    del candidate["function_name"]
    result = check_schema(candidate)
    assert not result.passed
    assert "function_name" in result.reason


def test_check_schema_rejects_a_bad_difficulty():
    result = check_schema(_dsa_candidate(difficulty="trivial"))
    assert not result.passed


def test_check_duplicate_accepts_a_novel_question():
    assert check_duplicate(_dsa_candidate(), existing_texts=["something else"]).passed


def test_check_duplicate_rejects_an_exact_match():
    candidate = _dsa_candidate()
    result = check_duplicate(candidate, existing_texts=[candidate["question"]])
    assert not result.passed


def test_check_duplicate_ignores_case_and_whitespace():
    candidate = _dsa_candidate()
    noisy = "   " + candidate["question"].upper().replace(" ", "   ") + "  "
    result = check_duplicate(candidate, existing_texts=[noisy])
    assert not result.passed


def test_check_correctness_accepts_a_solution_that_passes_every_case():
    assert check_correctness(_dsa_candidate()).passed


def test_check_correctness_rejects_a_solution_that_gets_the_wrong_answer():
    wrong = "def double_all(nums):\n    return nums\n"
    result = check_correctness(_dsa_candidate(reference_solution=wrong))
    assert not result.passed


def test_check_correctness_rejects_a_wrong_expected_value():
    # The failure class the runner gate exists to catch (ADR 0024): the code is
    # correct, but a test case asserts the wrong output. The correct solution
    # cannot reproduce the bad expected, so the candidate is rejected.
    bad_cases = [
        {"args": [[1, 2, 3]], "expected": [2, 4, 7]},
        {"args": [[]], "expected": []},
    ]
    result = check_correctness(_dsa_candidate(test_cases=bad_cases))
    assert not result.passed


def test_check_correctness_rejects_a_missing_reference_solution():
    candidate = _dsa_candidate()
    del candidate["reference_solution"]
    result = check_correctness(candidate)
    assert not result.passed
    assert "reference_solution" in result.reason


def test_check_correctness_rejects_a_solution_that_does_not_define_the_function():
    result = check_correctness(
        _dsa_candidate(reference_solution="def something_else():\n    return 1\n")
    )
    assert not result.passed


def test_gate_candidate_accepts_a_valid_candidate():
    assert gate_candidate(_dsa_candidate(), existing_texts=[]).passed


def test_gate_candidate_reports_schema_before_running_code():
    # A malformed candidate must fail on schema, not reach the runner (which
    # would need fields the schema guarantees). Ordering matters.
    candidate = _dsa_candidate()
    del candidate["function_name"]
    result = gate_candidate(candidate, existing_texts=[])
    assert not result.passed
    assert "function_name" in result.reason


def test_gate_batch_keeps_the_good_and_drops_the_bad():
    good = _dsa_candidate()
    bad = _dsa_candidate(
        question="Implement halve_all: return each value halved.",
        function_name="halve_all",
        reference_solution="def halve_all(nums):\n    return nums\n",  # wrong
    )
    batch = gate_batch([good, bad], existing_texts=[])
    assert good in batch.kept
    assert len(batch.rejected) == 1
    assert batch.rejected[0][0] is bad


def test_gate_batch_rejects_a_within_batch_duplicate():
    first = _dsa_candidate()
    second = _dsa_candidate()  # same question text as first
    batch = gate_batch([first, second], existing_texts=[])
    assert len(batch.kept) == 1
    assert len(batch.rejected) == 1
    assert "duplicate" in batch.rejected[0][1]


def _warm_up_candidate(**overrides):
    """A minimal, valid conceptual (warm-up) candidate; no code fields."""
    candidate = {
        "domain": "ml_genai",
        "topic": "bias-variance",
        "difficulty": "easy",
        "question": "What is regularization, and why does it help with overfitting?",
        "follow_up_hints": ["Ask about L1 versus L2"],
    }
    candidate.update(overrides)
    return candidate


def test_check_warm_up_schema_accepts_a_valid_candidate():
    assert check_warm_up_schema(_warm_up_candidate()).passed


def test_check_warm_up_schema_rejects_a_missing_field():
    candidate = _warm_up_candidate()
    del candidate["follow_up_hints"]
    result = check_warm_up_schema(candidate)
    assert not result.passed
    assert "follow_up_hints" in result.reason


def test_gate_warm_up_candidate_accepts_a_valid_candidate():
    assert gate_warm_up_candidate(_warm_up_candidate(), existing_texts=[]).passed


def test_gate_warm_up_needs_no_code_fields_or_reference_solution():
    # A conceptual question has no function_name/test_cases and no runner check;
    # it must still pass. This is the whole difference from the DSA gate.
    candidate = _warm_up_candidate()
    assert "function_name" not in candidate
    assert "reference_solution" not in candidate
    assert gate_warm_up_candidate(candidate, existing_texts=[]).passed


def test_gate_warm_up_rejects_a_duplicate():
    candidate = _warm_up_candidate()
    result = gate_warm_up_candidate(candidate, existing_texts=[candidate["question"]])
    assert not result.passed


def test_gate_batch_can_use_the_warm_up_gate():
    good = _warm_up_candidate()
    bad = _warm_up_candidate(difficulty="trivial")  # invalid difficulty fails schema
    batch = gate_batch([good, bad], existing_texts=[], gate=gate_warm_up_candidate)
    assert good in batch.kept
    assert len(batch.rejected) == 1
