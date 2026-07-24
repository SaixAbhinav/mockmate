"""Machine gates for offline question generation (ADR 0024).

A generated candidate question is checked by a machine before any human looks
at it. Candidates that fail are dropped and never surfaced. This module is part
of the offline pipeline: it imports from ``app`` but is never imported by it.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.questions import QuestionBankError, load_dsa_bank
from app.runner import run_tests

DEFAULT_MAX_WORDS = 50


@dataclass(frozen=True)
class GateResult:
    """One gate's verdict. ``reason`` describes the failure and is empty on pass."""

    passed: bool
    reason: str = ""


def check_schema(candidate: dict) -> GateResult:
    """The candidate must load as a valid DsaQuestion. Reuses the bank loader so
    there is one schema definition, not two (ADR 0024). The reference_solution
    is not part of the bank schema and is dropped before the check."""
    entry = {k: v for k, v in candidate.items() if k != "reference_solution"}
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "dsa.yaml").write_text(yaml.safe_dump([entry]), encoding="utf-8")
        try:
            load_dsa_bank(questions_dir=Path(tmp))
        except QuestionBankError as exc:
            return GateResult(False, str(exc))
    return GateResult(True)


def check_length(candidate: dict, max_words: int = DEFAULT_MAX_WORDS) -> GateResult:
    """Questions are read aloud by TTS (ADR 0004), so an over-long prompt is a
    poor spoken experience. Word count on the question text."""
    words = len(str(candidate.get("question", "")).split())
    if words > max_words:
        return GateResult(False, f"question is {words} words (max {max_words})")
    return GateResult(True)


def _normalize(text: str) -> str:
    """Fold case and collapse whitespace so trivially different phrasings of the
    same question text compare equal."""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def check_duplicate(candidate: dict, existing_texts: Iterable[str]) -> GateResult:
    """Reject a candidate whose question text matches one already seen — the
    existing bank or an earlier keeper in the same batch — ignoring case and
    whitespace. This is a text check; it does not catch two questions that probe
    the same idea in different words (ADR 0024 leaves that to human review)."""
    normalized = _normalize(candidate.get("question", ""))
    if normalized in {_normalize(t) for t in existing_texts}:
        return GateResult(False, "duplicate of an existing question")
    return GateResult(True)


def check_correctness(candidate: dict) -> GateResult:
    """The coding gate that earns ADR 0024: the emitted reference_solution must
    pass every emitted test case in the sandboxed runner (runner.py). This
    catches wrong ``expected`` values, signatures that contradict the prose, and
    tests that assert something other than what the question asks. The solution
    is only proof of coherence — it is discarded and never enters the bank."""
    solution = candidate.get("reference_solution")
    if not isinstance(solution, str) or not solution.strip():
        return GateResult(False, "no reference_solution to verify against")

    result = run_tests(
        solution,
        str(candidate.get("function_name", "")),
        list(candidate.get("test_cases", [])),
    )
    if result.status == "timeout":
        return GateResult(False, "reference_solution timed out")
    if result.status == "error":
        return GateResult(False, f"reference_solution failed to run: {result.error}")

    failed = sum(1 for r in result.results if not r.passed)
    if failed:
        return GateResult(
            False,
            f"reference_solution failed {failed} of {len(result.results)} cases",
        )
    return GateResult(True)


def gate_candidate(
    candidate: dict,
    *,
    existing_texts: Iterable[str],
    max_words: int = DEFAULT_MAX_WORDS,
) -> GateResult:
    """Run every gate in ADR 0024's order — schema, length, duplication, then
    the runner correctness check — and return the first failure, or a pass.
    Schema runs first so later gates can assume the fields they need exist."""
    schema = check_schema(candidate)
    if not schema.passed:
        return schema
    length = check_length(candidate, max_words=max_words)
    if not length.passed:
        return length
    duplicate = check_duplicate(candidate, existing_texts)
    if not duplicate.passed:
        return duplicate
    return check_correctness(candidate)


@dataclass(frozen=True)
class GatedBatch:
    """The outcome of gating a batch: keepers, and rejects with their reason."""

    kept: list[dict]
    rejected: list[tuple[dict, str]]


def gate_batch(
    candidates: Iterable[dict],
    existing_texts: Iterable[str] = (),
    *,
    max_words: int = DEFAULT_MAX_WORDS,
) -> GatedBatch:
    """Gate a whole batch. Accepted question texts accumulate into the seen set,
    so a later candidate that duplicates an earlier keeper in the same batch is
    itself rejected (ADR 0024: dedupe against the bank and within the batch)."""
    seen = [str(t) for t in existing_texts]
    kept: list[dict] = []
    rejected: list[tuple[dict, str]] = []
    for candidate in candidates:
        result = gate_candidate(candidate, existing_texts=seen, max_words=max_words)
        if result.passed:
            kept.append(candidate)
            seen.append(str(candidate.get("question", "")))
        else:
            rejected.append((candidate, result.reason))
    return GatedBatch(kept=kept, rejected=rejected)
