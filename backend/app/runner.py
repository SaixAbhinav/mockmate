"""Sandboxed test runner for the DSA round (ADR 0012/0016).

Candidate code runs in a subprocess: python -I, a temp working directory, a
hard timeout, and a scrubbed environment so the backend's API keys are never
visible to it. This is a guardrail for a self-hosted tool, not a hard
security boundary (no network blocking, no memory caps) - container
isolation is a later hardening day.

The harness writes per-case results to results.json in the temp dir; using a
file instead of stdout means candidate print() calls cannot corrupt the
result parse.
"""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 5.0
_MAX_ERROR_CHARS = 2000

# Exit codes the harness uses to distinguish "your code didn't load" from a
# harness crash (which would be our bug, not the candidate's).
_EXIT_CODE_FAILED_TO_LOAD = 3
_EXIT_FUNCTION_MISSING = 4

_HARNESS = """\
import json
import sys
import traceback

with open("cases.json", encoding="utf-8") as f:
    spec = json.load(f)

namespace = {}
with open("solution.py", encoding="utf-8") as f:
    code = f.read()
try:
    exec(compile(code, "solution.py", "exec"), namespace)
except BaseException:
    sys.stderr.write(traceback.format_exc())
    sys.exit(3)

func = namespace.get(spec["function_name"])
if not callable(func):
    sys.stderr.write("function %r is not defined" % spec["function_name"])
    sys.exit(4)

results = []
for case in spec["test_cases"]:
    entry = {"args": case["args"], "expected": case["expected"]}
    try:
        got = func(*case["args"])
        try:
            got = json.loads(json.dumps(got))  # tuples -> lists, etc.
        except (TypeError, ValueError):
            pass
        entry["got"] = repr(got)
        entry["passed"] = got == case["expected"]
    except BaseException as exc:
        entry["got"] = ("%s: %s" % (type(exc).__name__, exc))[:500]
        entry["passed"] = False
    results.append(entry)

with open("results.json", "w", encoding="utf-8") as f:
    json.dump(results, f)
"""


@dataclass(frozen=True)
class TestCaseResult:
    """One test case's outcome; got is a repr or an error string."""

    args: list
    expected: object
    got: str
    passed: bool


@dataclass(frozen=True)
class RunResult:
    """The whole run: ok (cases executed), error (code never ran), or timeout."""

    status: str  # "ok" | "error" | "timeout"
    error: str | None
    results: list[TestCaseResult]


def _scrubbed_env() -> dict[str, str]:
    # Candidate code can read os.environ, and ours holds API keys. Only what
    # the Python runtime itself needs crosses the boundary.
    keep = ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP")
    return {k: os.environ[k] for k in keep if k in os.environ}


def run_tests(
    code: str,
    function_name: str,
    test_cases: list[dict],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> RunResult:
    """Run candidate code against a question's test cases in a sandboxed
    subprocess. Synchronous - endpoint callers use asyncio.to_thread."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "solution.py").write_text(code, encoding="utf-8")
        (tmp_path / "harness.py").write_text(_HARNESS, encoding="utf-8")
        (tmp_path / "cases.json").write_text(
            json.dumps({"function_name": function_name, "test_cases": test_cases}),
            encoding="utf-8",
        )

        try:
            proc = subprocess.run(
                [sys.executable, "-I", "harness.py"],
                cwd=tmp,
                env=_scrubbed_env(),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                status="timeout",
                error=f"your code did not finish within {timeout_seconds:g} seconds",
                results=[],
            )

        if proc.returncode in (_EXIT_CODE_FAILED_TO_LOAD, _EXIT_FUNCTION_MISSING):
            return RunResult(
                status="error",
                error=(proc.stderr or "your code failed to run")[-_MAX_ERROR_CHARS:],
                results=[],
            )
        results_file = tmp_path / "results.json"
        if proc.returncode != 0 or not results_file.is_file():
            return RunResult(
                status="error",
                error=(proc.stderr or "the test run failed unexpectedly")[-_MAX_ERROR_CHARS:],
                results=[],
            )

        raw = json.loads(results_file.read_text(encoding="utf-8"))
        return RunResult(
            status="ok",
            error=None,
            results=[
                TestCaseResult(
                    args=entry["args"],
                    expected=entry["expected"],
                    got=entry["got"],
                    passed=entry["passed"],
                )
                for entry in raw
            ],
        )


def summarize_run(result: RunResult) -> str:
    """Compact text for the interviewer prompt and the transcript."""
    if result.status == "timeout":
        return "The code timed out before finishing the test cases."
    if result.status == "error":
        return f"The code failed to run: {result.error}"
    passed = sum(1 for r in result.results if r.passed)
    lines = [f"{passed} of {len(result.results)} test cases passed."]
    for r in result.results:
        if not r.passed:
            lines.append(f"- args={r.args!r} expected={r.expected!r} got={r.got}")
    return "\n".join(lines)
