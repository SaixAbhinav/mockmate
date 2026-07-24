"""Tests for the offline warm-up-generation CLI core (ADR 0024).

Same shape as the DSA CLI tests, but for conceptual questions: no code fields
and no runner correctness gate. A fake chat keeps it deterministic and keyless.
"""

import json

import pytest
import yaml

from scripts.generate_warm_up import build_parser, run

pytestmark = pytest.mark.anyio


def _reply(**overrides):
    candidate = {
        "question": "In plain terms, what problem does batch normalization solve during training?",
        "follow_up_hints": ["Ask about internal covariate shift"],
    }
    candidate.update(overrides)
    return json.dumps({"questions": [candidate]})


def _chat_returning(reply):
    async def chat(messages):
        return reply

    return chat


async def test_run_writes_a_kept_candidate_to_staging(tmp_path):
    out = tmp_path / "ml_genai.staging.yaml"
    report = await run(
        _chat_returning(_reply()),
        domain="ml_genai",
        topic="optimization",
        difficulty="medium",
        count=1,
        out_path=out,
    )
    assert report.kept == 1
    entries = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["domain"] == "ml_genai"
    assert entries[0]["topic"] == "optimization"


async def test_run_drops_a_candidate_that_fails_schema(tmp_path):
    out = tmp_path / "ml_genai.staging.yaml"
    # An empty follow_up_hints list fails the warm-up schema gate.
    report = await run(
        _chat_returning(_reply(follow_up_hints=[])),
        domain="ml_genai",
        topic="optimization",
        difficulty="medium",
        count=1,
        out_path=out,
    )
    assert report.kept == 0
    assert len(report.rejected) == 1
    assert not out.exists()


def test_parser_defaults_domain_and_reads_topic():
    args = build_parser().parse_args(["--topic", "rag"])
    assert args.topic == "rag"
    assert args.domain  # has a default so the common case needs only --topic
    assert args.difficulty in ("easy", "medium", "hard")
