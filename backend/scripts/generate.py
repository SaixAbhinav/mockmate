"""Offline DSA-question generation driver (ADR 0024).

Builds a topic-quota generation prompt, asks a provider for candidates, and
parses the reply into gate-ready candidate dicts. It does not decide what to
keep — that is the gates' job (scripts/gates.py). Part of the offline pipeline:
it imports from ``app`` but is never imported by it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.providers import GroqProvider
from app.questions import DsaQuestion, Question

# A provider seam: given chat messages, return the raw reply text. Kept as a
# plain callable so the drivers are testable without a live provider or API key;
# the CLIs wire this to a real provider via groq_chat (ADR 0024).
Chat = Callable[[list[dict[str, str]]], Awaitable[str]]


def groq_chat(*, max_tokens: int = 2000) -> Chat:
    """Wire the ``chat`` seam to Groq's transport for the offline CLIs. Reaches
    the provider's raw JSON completion directly — a dev script needs raw
    completion, not the graph's task-specific methods (ADR 0024). Needs
    GROQ_API_KEY; generation is an offline chore off the service's hot path."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise SystemExit("GROQ_API_KEY is not set: generation is an offline dev chore")
    provider = GroqProvider(key)

    async def chat(messages: list[dict[str, str]]) -> str:
        return await provider._chat_json(messages, max_tokens=max_tokens)

    return chat

GENERATION_SYSTEM_PROMPT = """\
You write Python coding-interview questions for a mock interviewer. The question \
text is read aloud to the candidate by text-to-speech, so keep it to one or two \
spoken sentences with no code blocks, symbols, or markdown.

Reply with a single JSON object of the form {"questions": [ ... ]}. Each entry \
must have exactly these fields:
- "question": the spoken prompt (plain sentences).
- "follow_up_hints": a non-empty list of short interviewer follow-up prompts.
- "function_name": the Python function the candidate implements.
- "signature": the full def line with type hints.
- "starter_code": a stub defining the function with a placeholder body.
- "test_cases": a non-empty list of {"args": [...], "expected": ...}, where args \
is the argument list and expected is the one correct return value (compared with \
==). Cover the empty/degenerate case.
- "reference_solution": correct Python defining function_name that returns the \
expected value for every test case. It is used only to verify the question and \
is then discarded.

Make each question self-contained and distinct from every example shown."""


class GenerationError(Exception):
    """The provider's reply could not be parsed into candidate questions."""


def _examples_block(examples: Sequence[DsaQuestion]) -> str:
    """Render existing bank questions as house-style few-shot references and an
    explicit do-not-overlap list (ADR 0024 steers coverage by topic quota)."""
    if not examples:
        return "There are no existing questions for this topic yet."
    lines = ["Existing questions for this topic — match their style, do not repeat them:"]
    for q in examples:
        lines.append(f"- {q.function_name}: {q.question}")
    return "\n".join(lines)


def build_generation_messages(
    topic: str,
    difficulty: str,
    count: int,
    examples: Sequence[DsaQuestion],
) -> list[dict[str, str]]:
    """Prompt for exactly ``count`` new ``difficulty`` questions on ``topic``,
    grounded in the existing bank entries for that topic."""
    user = (
        f"Write {count} new {difficulty} Python coding questions on the topic "
        f'"{topic}".\n\n{_examples_block(examples)}'
    )
    return [
        {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_candidates(content: str) -> list[dict]:
    """Pull the candidate list out of a provider reply. Shape only — field-level
    validity is the gates' job (a lenient parser here means a malformed field
    is rejected by the schema gate with a clear reason, not swallowed here)."""
    try:
        data = json.loads(content)
        questions = data["questions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GenerationError(f"malformed generation response: {content!r}") from exc
    if not isinstance(questions, list) or not questions:
        raise GenerationError(f"expected a non-empty question list, got {questions!r}")
    for entry in questions:
        if not isinstance(entry, dict):
            raise GenerationError(f"each candidate must be an object, got {entry!r}")
    return questions


async def generate_candidates(
    chat: Chat,
    *,
    topic: str,
    difficulty: str,
    count: int,
    examples: Sequence[DsaQuestion] = (),
) -> list[dict]:
    """Ask ``chat`` for ``count`` candidates on ``topic`` and return them ready
    for the gates. The domain/topic/difficulty quota fields are stamped by the
    driver rather than trusted to the model's echo, so a candidate can never be
    filed under the wrong topic."""
    messages = build_generation_messages(topic, difficulty, count, examples)
    candidates = parse_candidates(await chat(messages))
    for candidate in candidates:
        candidate["domain"] = "dsa"
        candidate["topic"] = topic
        candidate["difficulty"] = difficulty
    return candidates


WARM_UP_SYSTEM_PROMPT = """\
You write short conceptual interview questions for a spoken mock interview. The \
question is read aloud by text-to-speech, so keep it to one or two plain \
sentences — no code, symbols, or markdown. These are discussion questions, not \
coding exercises.

Reply with a single JSON object of the form {"questions": [ ... ]}. Each entry \
must have exactly these fields:
- "question": the spoken prompt (plain sentences).
- "follow_up_hints": a non-empty list of short prompts the interviewer can use \
to probe deeper; they ground follow-ups and are not read verbatim.

Make each question self-contained and distinct from every example shown."""


def _warm_examples_block(examples: Sequence[Question]) -> str:
    if not examples:
        return "There are no existing questions for this topic yet."
    lines = ["Existing questions for this topic — match their style, do not repeat them:"]
    for q in examples:
        lines.append(f"- {q.question}")
    return "\n".join(lines)


def build_warm_up_messages(
    domain: str,
    topic: str,
    difficulty: str,
    count: int,
    examples: Sequence[Question],
) -> list[dict[str, str]]:
    """Prompt for ``count`` new ``difficulty`` conceptual questions on ``topic``
    within ``domain``, grounded in the existing bank entries for that topic."""
    user = (
        f'Write {count} new {difficulty} conceptual questions on the topic "{topic}" '
        f'in the "{domain}" domain.\n\n{_warm_examples_block(examples)}'
    )
    return [
        {"role": "system", "content": WARM_UP_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def generate_warm_up_candidates(
    chat: Chat,
    *,
    domain: str,
    topic: str,
    difficulty: str,
    count: int,
    examples: Sequence[Question] = (),
) -> list[dict]:
    """Conceptual counterpart to ``generate_candidates``: no code fields, no
    reference solution. Stamps the quota fields the same way."""
    messages = build_warm_up_messages(domain, topic, difficulty, count, examples)
    candidates = parse_candidates(await chat(messages))
    for candidate in candidates:
        candidate["domain"] = domain
        candidate["topic"] = topic
        candidate["difficulty"] = difficulty
    return candidates


@dataclass(frozen=True)
class Report:
    """What one generation run produced: how many were staged, and why the rest
    were dropped (each as a question snippet and the gate's reason)."""

    kept: int
    rejected: list[tuple[str, str]]
    staging_path: Path


def append_staging(out_path: Path, kept: list[dict]) -> None:
    """Append kept candidates to a staging YAML, dropping any reference solution
    (proof of coherence only, never banked — ADR 0024). Shared by both CLIs; it
    never touches a real bank file."""
    existing = []
    if out_path.exists():
        existing = yaml.safe_load(out_path.read_text(encoding="utf-8")) or []
    entries = existing + [
        {k: v for k, v in candidate.items() if k != "reference_solution"}
        for candidate in kept
    ]
    out_path.write_text(
        yaml.safe_dump(entries, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
