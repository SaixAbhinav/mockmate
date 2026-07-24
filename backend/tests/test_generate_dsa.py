"""Tests for the offline DSA-generation CLI core (ADR 0024).

The CLI's core — load bank, generate, gate, write staging, report — is tested
with an injected fake chat so it needs no API key. The provider wiring and
argument parsing around it are a thin I/O shell, exercised separately.
"""

import json

import pytest
import yaml

from scripts.generate_dsa import build_parser, run

pytestmark = pytest.mark.anyio

_CORRECT = (
    "def prefix_max(nums):\n"
    "    out, best = [], None\n"
    "    for n in nums:\n"
    "        best = n if best is None else max(best, n)\n"
    "        out.append(best)\n"
    "    return out\n"
)


def _reply(**overrides):
    candidate = {
        "question": "Implement prefix_max: return the running maximums of a list.",
        "follow_up_hints": ["Ask about the time complexity"],
        "function_name": "prefix_max",
        "signature": "def prefix_max(nums: list[int]) -> list[int]:",
        "starter_code": "def prefix_max(nums):\n    pass\n",
        "test_cases": [{"args": [[1, 3, 2]], "expected": [1, 3, 3]}],
        "reference_solution": _CORRECT,
    }
    candidate.update(overrides)
    return json.dumps({"questions": [candidate]})


def _chat_returning(reply):
    async def chat(messages):
        return reply

    return chat


def test_parser_reads_topic_count_and_difficulty():
    args = build_parser().parse_args(
        ["--topic", "stacks", "--count", "7", "--difficulty", "hard"]
    )
    assert args.topic == "stacks"
    assert args.count == 7
    assert args.difficulty == "hard"


def test_parser_defaults_count_and_difficulty():
    args = build_parser().parse_args(["--topic", "arrays"])
    assert args.count > 0
    assert args.difficulty in ("easy", "medium", "hard")


def test_parser_rejects_an_unknown_difficulty():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--topic", "arrays", "--difficulty", "trivial"])


async def test_run_writes_a_kept_candidate_to_staging(tmp_path):
    out = tmp_path / "dsa.staging.yaml"
    report = await run(
        _chat_returning(_reply()),
        topic="arrays",
        difficulty="medium",
        count=1,
        out_path=out,
    )
    assert report.kept == 1
    entries = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["function_name"] == "prefix_max"
    assert entries[0]["topic"] == "arrays"


async def test_run_strips_the_reference_solution_before_staging(tmp_path):
    out = tmp_path / "dsa.staging.yaml"
    await run(
        _chat_returning(_reply()),
        topic="arrays",
        difficulty="medium",
        count=1,
        out_path=out,
    )
    entries = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "reference_solution" not in entries[0]


async def test_run_drops_a_candidate_that_fails_a_gate(tmp_path):
    out = tmp_path / "dsa.staging.yaml"
    wrong = _reply(reference_solution="def prefix_max(nums):\n    return nums\n")
    report = await run(
        _chat_returning(wrong),
        topic="arrays",
        difficulty="medium",
        count=1,
        out_path=out,
    )
    assert report.kept == 0
    assert len(report.rejected) == 1
    assert not out.exists()


async def test_run_appends_across_runs(tmp_path):
    out = tmp_path / "dsa.staging.yaml"
    await run(
        _chat_returning(_reply()),
        topic="arrays",
        difficulty="medium",
        count=1,
        out_path=out,
    )
    second = _reply(
        question="Implement prefix_min: return the running minimums of a list.",
        function_name="prefix_min",
        signature="def prefix_min(nums: list[int]) -> list[int]:",
        starter_code="def prefix_min(nums):\n    pass\n",
        test_cases=[{"args": [[3, 1, 2]], "expected": [3, 1, 1]}],
        reference_solution=(
            "def prefix_min(nums):\n"
            "    out, best = [], None\n"
            "    for n in nums:\n"
            "        best = n if best is None else min(best, n)\n"
            "        out.append(best)\n"
            "    return out\n"
        ),
    )
    await run(
        _chat_returning(second),
        topic="arrays",
        difficulty="medium",
        count=1,
        out_path=out,
    )
    entries = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(entries) == 2
