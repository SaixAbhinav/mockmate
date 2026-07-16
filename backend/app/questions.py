"""Question bank loader (ADR 0003 schema, ADR 0008 source).

Curated YAML per domain, validated on load so a malformed entry fails fast
at startup rather than surfacing as a confusing runtime error mid-interview.
"""

import random
from dataclasses import dataclass
from pathlib import Path

import yaml

DIFFICULTIES = ("easy", "medium", "hard")
DEFAULT_QUESTIONS_DIR = Path(__file__).parent / "questions"


class QuestionBankError(Exception):
    """Raised when a domain's question bank is missing or malformed."""


@dataclass(frozen=True)
class Question:
    domain: str
    topic: str
    difficulty: str
    question: str
    follow_up_hints: list[str]


def load_bank(domain: str, questions_dir: Path = DEFAULT_QUESTIONS_DIR) -> list[Question]:
    path = Path(questions_dir) / f"{domain}.yaml"
    if not path.is_file():
        raise QuestionBankError(f"no question bank for domain {domain!r} at {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise QuestionBankError(f"{path} must contain a YAML list of questions")

    questions = []
    for i, entry in enumerate(raw):
        try:
            required = {
                "domain": entry["domain"],
                "topic": entry["topic"],
                "difficulty": entry["difficulty"],
                "question": entry["question"],
                "follow_up_hints": entry["follow_up_hints"],
            }
        except (KeyError, TypeError) as exc:
            raise QuestionBankError(f"{path} entry {i}: missing field {exc}") from exc

        if required["difficulty"] not in DIFFICULTIES:
            raise QuestionBankError(
                f"{path} entry {i}: difficulty must be one of {DIFFICULTIES}, "
                f"got {required['difficulty']!r}"
            )
        if not isinstance(required["follow_up_hints"], list) or not required["follow_up_hints"]:
            raise QuestionBankError(
                f"{path} entry {i}: follow_up_hints must be a non-empty list"
            )

        questions.append(Question(**required))

    return questions


def plan_warm_up(
    domain: str,
    *,
    seed: int | None = None,
    questions_dir: Path = DEFAULT_QUESTIONS_DIR,
) -> list[Question]:
    """Curated fallback for the warm-up round (ADR 0012/0015): a seeded draw
    of 3 questions from the domain's bank, sorted easy->hard.

    Used when no resume was uploaded or resume-grounded generation was
    unavailable. The old 6-8 question domain round this bank used to power
    was replaced by the phased Session (ADR 0012).
    """
    bank = load_bank(domain, questions_dir=questions_dir)
    rng = random.Random(seed)
    drawn = rng.sample(bank, min(3, len(bank)))
    return sorted(drawn, key=lambda q: DIFFICULTIES.index(q.difficulty))
