"""Offline warm-up (conceptual) question generation CLI (ADR 0024).

The conceptual counterpart to generate_dsa: the same generate -> gate -> stage
-> review pipeline, but for warm-up Questions, which have no code and nothing a
runner can verify. Human review therefore carries more of the weight here (the
gates only enforce schema, spoken length, and de-duplication).

    cd backend && uv run python -m scripts.generate_warm_up --topic rag --count 5

Part of the offline pipeline: imports from ``app`` but is never imported by it.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.questions import (
    DEFAULT_QUESTIONS_DIR,
    DIFFICULTIES,
    FALLBACK_DOMAIN,
    load_bank,
)
from scripts.gates import DEFAULT_MAX_WORDS, gate_batch, gate_warm_up_candidate
from scripts.generate import (
    Chat,
    Report,
    append_staging,
    generate_warm_up_candidates,
    groq_chat,
)


def _staging_for(domain: str) -> Path:
    return Path(__file__).parent / f"{domain}.staging.yaml"


async def run(
    chat: Chat,
    *,
    domain: str,
    topic: str,
    difficulty: str,
    count: int,
    out_path: Path | None = None,
    questions_dir: Path = DEFAULT_QUESTIONS_DIR,
    max_words: int = DEFAULT_MAX_WORDS,
) -> Report:
    """Generate, gate, and stage conceptual questions for one domain/topic.
    Existing bank entries for the topic seed the prompt as few-shot; every
    existing question in the domain seeds the dedupe check."""
    out_path = out_path or _staging_for(domain)
    bank = load_bank(domain, questions_dir=questions_dir)
    examples = [q for q in bank if q.topic == topic]
    existing_texts = [q.question for q in bank]

    candidates = await generate_warm_up_candidates(
        chat, domain=domain, topic=topic, difficulty=difficulty, count=count,
        examples=examples,
    )
    batch = gate_batch(
        candidates, existing_texts, gate=gate_warm_up_candidate, max_words=max_words
    )

    if batch.kept:
        append_staging(out_path, batch.kept)

    rejected = [
        (str(candidate.get("question", ""))[:80], reason)
        for candidate, reason in batch.rejected
    ]
    return Report(kept=len(batch.kept), rejected=rejected, staging_path=out_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_warm_up",
        description="Generate conceptual warm-up questions offline, gate them, and "
        "stage the survivors for review (ADR 0024).",
    )
    parser.add_argument("--topic", required=True, help="topic to generate for, e.g. rag")
    parser.add_argument(
        "--domain", default=FALLBACK_DOMAIN, help="question domain (bank to draw few-shot from)"
    )
    parser.add_argument("--count", type=int, default=5, help="how many to ask for")
    parser.add_argument(
        "--difficulty", choices=DIFFICULTIES, default="medium", help="target difficulty"
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="staging YAML to append to (defaults to <domain>.staging.yaml)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = asyncio.run(
        run(
            groq_chat(),
            domain=args.domain,
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
