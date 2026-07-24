"""Offline DSA-question generation driver (ADR 0024).

Builds a topic-quota generation prompt, asks a provider for candidates, and
parses the reply into gate-ready candidate dicts. It does not decide what to
keep — that is the gates' job (scripts/gates.py). Part of the offline pipeline:
it imports from ``app`` but is never imported by it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence

from app.questions import DsaQuestion

# A provider seam: given chat messages, return the raw reply text. Kept as a
# plain callable so the driver is testable without a live provider or API key;
# the CLI (a later PR) wires this to a real provider (ADR 0024).
Chat = Callable[[list[dict[str, str]]], Awaitable[str]]

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
