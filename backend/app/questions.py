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


@dataclass(frozen=True)
class DsaQuestion:
    """A coding-round question (ADR 0012/0016): the ADR 0003 fields plus what
    the editor and the runner need."""

    domain: str
    topic: str
    difficulty: str
    question: str
    follow_up_hints: list[str]
    function_name: str
    signature: str
    starter_code: str
    test_cases: list[dict]


def load_dsa_bank(questions_dir: Path = DEFAULT_QUESTIONS_DIR) -> list[DsaQuestion]:
    """Load and validate the DSA bank (dsa.yaml), failing fast on a malformed
    entry — same posture as load_bank, stricter schema."""
    path = Path(questions_dir) / "dsa.yaml"
    if not path.is_file():
        raise QuestionBankError(f"no DSA question bank at {path}")

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
                "function_name": entry["function_name"],
                "signature": entry["signature"],
                "starter_code": entry["starter_code"],
                "test_cases": entry["test_cases"],
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
        if not str(required["function_name"]).isidentifier():
            raise QuestionBankError(
                f"{path} entry {i}: function_name must be a Python identifier"
            )
        for field in ("signature", "starter_code"):
            if not isinstance(required[field], str) or not required[field].strip():
                raise QuestionBankError(
                    f"{path} entry {i}: {field} must be a non-empty string"
                )
        cases = required["test_cases"]
        if not isinstance(cases, list) or not cases:
            raise QuestionBankError(
                f"{path} entry {i}: test_cases must be a non-empty list"
            )
        for j, case in enumerate(cases):
            if not isinstance(case, dict) or "expected" not in case:
                raise QuestionBankError(
                    f"{path} entry {i} case {j}: needs 'args' and 'expected'"
                )
            if not isinstance(case.get("args"), list):
                raise QuestionBankError(
                    f"{path} entry {i} case {j}: args must be a list"
                )

        questions.append(DsaQuestion(**required))

    return questions


def plan_dsa(
    *,
    seed: int | None = None,
    questions_dir: Path = DEFAULT_QUESTIONS_DIR,
) -> list[DsaQuestion]:
    """The DSA round's draw (ADR 0012): one easy question, then one medium or
    hard one, seeded so tests stay deterministic."""
    bank = load_dsa_bank(questions_dir=questions_dir)
    easy = [q for q in bank if q.difficulty == "easy"]
    harder = [q for q in bank if q.difficulty in ("medium", "hard")]
    if not easy or not harder:
        raise QuestionBankError("the DSA bank needs at least one easy and one medium/hard question")
    rng = random.Random(seed)
    return [rng.choice(easy), rng.choice(harder)]
