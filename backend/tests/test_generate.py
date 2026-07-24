"""Tests for the offline DSA-generation driver (ADR 0024).

The driver builds a topic-quota prompt, asks a provider for candidates, and
parses the reply into gate-ready dicts. It does not decide what to keep — that
is the gates' job. A fake chat callable stands in for a real provider so the
tests are deterministic and need no API key.
"""

import json

import pytest

from app.questions import DsaQuestion, Question
from scripts.gates import gate_batch, gate_warm_up_candidate
from scripts.generate import (
    GenerationError,
    build_generation_messages,
    build_warm_up_messages,
    generate_candidates,
    generate_warm_up_candidates,
    parse_candidates,
)

pytestmark = pytest.mark.anyio


def _example(**overrides):
    """A bank question used as a few-shot / don't-overlap example."""
    fields = dict(
        domain="dsa",
        topic="arrays",
        difficulty="easy",
        question="Implement running_sum: return the prefix sums of a list.",
        follow_up_hints=["Ask about the time complexity"],
        function_name="running_sum",
        signature="def running_sum(nums: list[int]) -> list[int]:",
        starter_code="def running_sum(nums):\n    pass\n",
        test_cases=[{"args": [[1, 2, 3]], "expected": [1, 3, 6]}],
    )
    fields.update(overrides)
    return DsaQuestion(**fields)


def _response(**candidate_overrides):
    """A well-formed provider reply carrying one DSA candidate."""
    candidate = {
        "question": "Implement prefix_max: return the running maximums of a list.",
        "follow_up_hints": ["Ask about the time complexity"],
        "function_name": "prefix_max",
        "signature": "def prefix_max(nums: list[int]) -> list[int]:",
        "starter_code": "def prefix_max(nums):\n    pass\n",
        "test_cases": [{"args": [[1, 3, 2]], "expected": [1, 3, 3]}],
        "reference_solution": "def prefix_max(nums):\n    pass\n",
    }
    candidate.update(candidate_overrides)
    return json.dumps({"questions": [candidate]})


def test_parse_candidates_extracts_the_question_list():
    result = parse_candidates(_response())
    assert len(result) == 1
    assert result[0]["function_name"] == "prefix_max"


def test_parse_candidates_rejects_non_json():
    with pytest.raises(GenerationError):
        parse_candidates("not json at all")


def test_parse_candidates_rejects_a_missing_questions_key():
    with pytest.raises(GenerationError):
        parse_candidates(json.dumps({"items": []}))


def test_parse_candidates_rejects_an_empty_batch():
    with pytest.raises(GenerationError):
        parse_candidates(json.dumps({"questions": []}))


def test_parse_candidates_rejects_a_non_object_candidate():
    with pytest.raises(GenerationError):
        parse_candidates(json.dumps({"questions": ["just a string"]}))


def test_build_messages_states_topic_difficulty_and_count():
    messages = build_generation_messages("stacks", "medium", 5, examples=[])
    text = " ".join(m["content"] for m in messages)
    assert "stacks" in text
    assert "medium" in text
    assert "5" in text


def test_build_messages_shows_examples_to_steer_style_and_avoid_overlap():
    messages = build_generation_messages("arrays", "easy", 3, examples=[_example()])
    text = " ".join(m["content"] for m in messages)
    assert "running_sum" in text


def test_build_messages_asks_for_a_reference_solution():
    # The correctness gate needs one; the prompt must request it.
    messages = build_generation_messages("arrays", "easy", 3, examples=[])
    text = " ".join(m["content"] for m in messages).lower()
    assert "reference_solution" in text


async def test_generate_candidates_returns_parsed_and_stamped():
    async def fake_chat(messages):
        return _response()

    candidates = await generate_candidates(
        fake_chat, topic="arrays", difficulty="medium", count=1, examples=[]
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["function_name"] == "prefix_max"
    # The driver stamps the quota fields rather than trusting the model to echo.
    assert candidate["domain"] == "dsa"
    assert candidate["topic"] == "arrays"
    assert candidate["difficulty"] == "medium"


async def test_generate_candidates_feeds_the_built_prompt_to_chat():
    seen = {}

    async def fake_chat(messages):
        seen["messages"] = messages
        return _response()

    await generate_candidates(
        fake_chat, topic="stacks", difficulty="hard", count=2, examples=[]
    )
    text = " ".join(m["content"] for m in seen["messages"])
    assert "stacks" in text
    assert "hard" in text


async def test_generate_candidates_propagates_a_malformed_reply():
    async def fake_chat(messages):
        return "not json"

    with pytest.raises(GenerationError):
        await generate_candidates(
            fake_chat, topic="arrays", difficulty="easy", count=1, examples=[]
        )


def _warm_example(**overrides):
    fields = dict(
        domain="ml_genai",
        topic="bias-variance",
        difficulty="easy",
        question="What is overfitting, and how would you detect it?",
        follow_up_hints=["Ask about train vs validation loss"],
    )
    fields.update(overrides)
    return Question(**fields)


def _warm_reply(**overrides):
    candidate = {
        "question": "What is regularization, and why does it help with overfitting?",
        "follow_up_hints": ["Ask about L1 versus L2"],
    }
    candidate.update(overrides)
    return json.dumps({"questions": [candidate]})


def test_build_warm_up_messages_states_domain_topic_difficulty_and_count():
    messages = build_warm_up_messages(
        "ml_genai", "embeddings", "medium", 4, examples=[]
    )
    text = " ".join(m["content"] for m in messages)
    assert "ml_genai" in text
    assert "embeddings" in text
    assert "medium" in text
    assert "4" in text


def test_build_warm_up_messages_does_not_ask_for_code():
    # Conceptual questions have no code fields; the prompt must not request them.
    messages = build_warm_up_messages("ml_genai", "rag", "easy", 3, examples=[])
    text = " ".join(m["content"] for m in messages).lower()
    assert "reference_solution" not in text
    assert "test_cases" not in text


async def test_generate_warm_up_candidates_returns_parsed_and_stamped():
    async def fake_chat(messages):
        return _warm_reply()

    candidates = await generate_warm_up_candidates(
        fake_chat, domain="ml_genai", topic="rag", difficulty="hard", count=1, examples=[]
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["domain"] == "ml_genai"
    assert candidate["topic"] == "rag"
    assert candidate["difficulty"] == "hard"


async def test_generated_warm_up_candidate_survives_the_warm_up_gate():
    async def fake_chat(messages):
        return _warm_reply()

    candidates = await generate_warm_up_candidates(
        fake_chat, domain="ml_genai", topic="bias-variance", difficulty="easy",
        count=1, examples=[],
    )
    batch = gate_batch(candidates, existing_texts=[], gate=gate_warm_up_candidate)
    assert len(batch.kept) == 1
    assert not batch.rejected


async def test_generated_candidate_with_a_correct_solution_survives_the_gates():
    # The seam PR 2 exists for: the driver's output is gate-ready. A candidate
    # whose reference_solution actually satisfies its test cases is kept.
    solved = _response(
        reference_solution=(
            "def prefix_max(nums):\n"
            "    out, best = [], None\n"
            "    for n in nums:\n"
            "        best = n if best is None else max(best, n)\n"
            "        out.append(best)\n"
            "    return out\n"
        )
    )

    async def fake_chat(messages):
        return solved

    candidates = await generate_candidates(
        fake_chat, topic="arrays", difficulty="medium", count=1, examples=[]
    )
    batch = gate_batch(candidates, existing_texts=[])
    assert len(batch.kept) == 1
    assert not batch.rejected
