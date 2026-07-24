"""Offline DSA-generation CLI (ADR 0024).

Ties the pipeline together: read the existing bank for topic few-shot and
dedupe context, ask a provider for candidates, run every machine gate, and
append the survivors to a gitignored staging YAML for a human to review into the
real bank. The reference solution that proved each coding question is discarded
before staging — it is never committed alongside the question it answers.

Run it as a dev chore (needs a provider key; spends free-tier quota):

    cd backend && uv run python -m scripts.generate_dsa --topic arrays --count 5

Part of the offline pipeline: imports from ``app`` but is never imported by it.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.questions import DEFAULT_QUESTIONS_DIR, DIFFICULTIES, load_dsa_bank
from scripts.gates import DEFAULT_MAX_WORDS, gate_batch
from scripts.generate import Report, append_staging, generate_candidates, groq_chat

DEFAULT_STAGING = Path(__file__).parent / "dsa.staging.yaml"


async def run(
    chat: Chat,
    *,
    topic: str,
    difficulty: str,
    count: int,
    out_path: Path = DEFAULT_STAGING,
    questions_dir: Path = DEFAULT_QUESTIONS_DIR,
    max_words: int = DEFAULT_MAX_WORDS,
) -> Report:
    """Generate, gate, and stage. Existing bank entries for the topic seed the
    prompt as house-style few-shot; every existing question seeds the dedupe
    check so a generated near-copy is dropped."""
    bank = load_dsa_bank(questions_dir=questions_dir)
    examples = [q for q in bank if q.topic == topic]
    existing_texts = [q.question for q in bank]

    candidates = await generate_candidates(
        chat, topic=topic, difficulty=difficulty, count=count, examples=examples
    )
    batch = gate_batch(candidates, existing_texts, max_words=max_words)

    if batch.kept:
        append_staging(out_path, batch.kept)

    rejected = [
        (str(candidate.get("question", ""))[:80], reason)
        for candidate, reason in batch.rejected
    ]
    return Report(kept=len(batch.kept), rejected=rejected, staging_path=out_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_dsa",
        description="Generate DSA coding questions offline, gate them, and stage "
        "the survivors for review (ADR 0024).",
    )
    parser.add_argument("--topic", required=True, help="topic to generate for, e.g. arrays")
    parser.add_argument("--count", type=int, default=5, help="how many to ask for")
    parser.add_argument(
        "--difficulty", choices=DIFFICULTIES, default="medium", help="target difficulty"
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_STAGING, help="staging YAML to append to"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = asyncio.run(
        run(
            groq_chat(),
            topic=args.topic,
            difficulty=args.difficulty,
            count=args.count,
            out_path=args.out,
        )
    )
    print(f"kept {report.kept} -> {report.staging_path}")
    for snippet, reason in report.rejected:
        print(f"  dropped ({reason}): {snippet}")


if __name__ == "__main__":
    main()
