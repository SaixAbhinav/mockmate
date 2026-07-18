from textwrap import dedent

from app.runner import run_tests, summarize_run

CASES = [
    {"args": [[1, 2, 3]], "expected": [1, 3, 6]},
    {"args": [[]], "expected": []},
]


def test_passing_solution_passes_every_case():
    code = dedent("""
        def running_sum(nums):
            total, out = 0, []
            for n in nums:
                total += n
                out.append(total)
            return out
    """)

    result = run_tests(code, "running_sum", CASES)

    assert result.status == "ok"
    assert [r.passed for r in result.results] == [True, True]


def test_wrong_answer_fails_with_got_value():
    result = run_tests("def running_sum(nums):\n    return nums\n", "running_sum", CASES)

    assert result.status == "ok"
    assert result.results[0].passed is False
    assert "[1, 2, 3]" in result.results[0].got


def test_exception_in_candidate_function_fails_that_case():
    code = "def running_sum(nums):\n    return nums[999]\n"

    result = run_tests(code, "running_sum", CASES)

    assert result.status == "ok"
    assert result.results[0].passed is False
    assert "IndexError" in result.results[0].got


def test_syntax_error_reports_status_error():
    result = run_tests("def running_sum(nums)\n    oops\n", "running_sum", CASES)

    assert result.status == "error"
    assert result.results == []
    assert "SyntaxError" in result.error


def test_missing_function_reports_status_error():
    result = run_tests("x = 1\n", "running_sum", CASES)

    assert result.status == "error"
    assert "running_sum" in result.error


def test_infinite_loop_times_out():
    code = "def running_sum(nums):\n    while True:\n        pass\n"

    result = run_tests(code, "running_sum", CASES, timeout_seconds=1.0)

    assert result.status == "timeout"


def test_candidate_prints_do_not_corrupt_results():
    code = dedent("""
        def running_sum(nums):
            print("debugging!", nums)
            total, out = 0, []
            for n in nums:
                total += n
                out.append(total)
            return out
    """)

    result = run_tests(code, "running_sum", CASES)

    assert result.status == "ok"
    assert all(r.passed for r in result.results)


def test_tuple_return_is_normalized_to_match_list_expected():
    code = "def pair(a, b):\n    return (a, b)\n"

    result = run_tests(code, "pair", [{"args": [1, 2], "expected": [1, 2]}])

    assert result.results[0].passed is True


def test_candidate_code_cannot_read_backend_env(monkeypatch):
    # The backend process holds API keys; the runner subprocess must get a
    # scrubbed environment (ADR 0016), not an inherited one.
    monkeypatch.setenv("FAKE_SECRET_KEY", "sk-leak-me")
    code = dedent("""
        import os

        def leak():
            return os.environ.get("FAKE_SECRET_KEY")
    """)

    result = run_tests(code, "leak", [{"args": [], "expected": None}])

    assert result.status == "ok"
    assert result.results[0].passed is True  # the secret was not visible


def test_summarize_run_reports_failures_compactly():
    result = run_tests("def running_sum(nums):\n    return nums\n", "running_sum", CASES)

    summary = summarize_run(result)

    assert "1 of 2" in summary
    assert "expected" in summary
