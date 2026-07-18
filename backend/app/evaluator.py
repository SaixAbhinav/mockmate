"""Evaluator agent: scores a completed Session against the rubric (ADR 0011).

Where the interviewer graph *branches* (one path per Turn), this one *fans out*:
each completed question is scored by its own concurrent LLM call dispatched with
the Send API, the results are gathered through an `operator.add` reducer on
`scores`, and one call assesses the Session as a whole.

Nodes here return only the keys they change. Spreading the whole state
(`{**state, ...}`) would re-emit `scores` and the reducer would add the list to
itself.
"""

import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from .providers import DIMENSIONS, LLMProvider, ProviderError, ProviderUnavailableError

logger = logging.getLogger(__name__)


class EvaluationState(TypedDict):
    """State for one Session's evaluation pass."""

    session_id: str
    domain: str
    completed: list[dict]
    units: list[dict]
    scores: Annotated[list[dict], operator.add]
    assessment: str
    strengths: list[str]
    improvements: list[str]
    assessment_retryable: bool


def aggregate_scores(scores: list[dict]) -> dict[str, float | None]:
    """Mean per Dimension over scored questions only.

    Skipped (never answered) and unscored (the provider failed) questions are
    excluded — you cannot rate the correctness of nothing. Coverage, reported
    separately, is what exposes a Candidate who simply disengaged.
    """
    scored = [s for s in scores if not s.get("skipped") and not s.get("unscored")]
    if not scored:
        return {dimension: None for dimension in DIMENSIONS}
    return {
        dimension: round(sum(s[dimension] for s in scored) / len(scored), 1)
        for dimension in DIMENSIONS
    }


def build_evaluator_graph(provider: LLMProvider):
    """Compile the fan-out/gather evaluation graph for the given provider."""

    def plan_evaluation(state: EvaluationState) -> dict:
        units, skipped = [], []
        for index, record in enumerate(state["completed"]):
            base = {
                "index": index,
                "question": record["question"],
                "topic": record["topic"],
                "difficulty": record["difficulty"],
            }
            if record["answered"]:
                units.append(
                    {
                        **base,
                        "follow_up_hints": record["follow_up_hints"],
                        "answers": record["answers"],
                    }
                )
            else:
                skipped.append({**base, "skipped": True})
        return {"units": units, "scores": skipped}

    def fan_out_to_scorers(state: EvaluationState):
        if not state["units"]:
            return "assess"
        return [Send("score_answer", {"unit": unit}) for unit in state["units"]]

    async def score_answer(payload: dict) -> dict:
        unit = payload["unit"]
        base = {
            "index": unit["index"],
            "question": unit["question"],
            "topic": unit["topic"],
            "difficulty": unit["difficulty"],
        }
        try:
            score = await provider.evaluate_answer(
                question=unit["question"],
                follow_up_hints=unit["follow_up_hints"],
                answers=unit["answers"],
            )
            scored = {
                **base,
                "correctness": score.correctness,
                "depth": score.depth,
                "clarity": score.clarity,
                "comment": score.comment,
            }
        except ProviderError as exc:
            # Base class on purpose: malformed or unavailable, this one question
            # is unscored and the Evaluation still renders (ADR 0013).
            # Never logger.exception here — a chained httpx traceback can carry
            # Gemini's API key.
            logger.warning("could not score %r: %s", unit["question"], exc)
            scored = {**base, "unscored": True, "retryable": isinstance(exc, ProviderUnavailableError)}
        return {"scores": [scored]}

    async def assess(state: EvaluationState) -> dict:
        ordered = sorted(state["scores"], key=lambda s: s["index"])
        try:
            result = await provider.assess_session(ordered)
            return {
                "assessment": result.assessment,
                "strengths": list(result.strengths),
                "improvements": list(result.improvements),
                "assessment_retryable": False,
            }
        except ProviderError as exc:
            logger.warning("could not assess session: %s", exc)
            return {
                "assessment": "Could not generate an overall assessment for this interview.",
                "strengths": [],
                "improvements": [],
                "assessment_retryable": isinstance(exc, ProviderUnavailableError),
            }

    graph = StateGraph(EvaluationState)
    graph.add_node("plan_evaluation", plan_evaluation)
    graph.add_node("score_answer", score_answer)
    graph.add_node("assess", assess)

    graph.set_entry_point("plan_evaluation")
    graph.add_conditional_edges(
        "plan_evaluation", fan_out_to_scorers, ["score_answer", "assess"]
    )
    graph.add_edge("score_answer", "assess")
    graph.add_edge("assess", END)

    return graph.compile()


async def evaluate_session(
    compiled_graph, session_id: str, domain: str, completed: list[dict]
) -> dict:
    """Run the evaluation pass and return the Candidate-facing Evaluation."""
    # The intro is an ice-breaker and the DSA round is scored by a future
    # code-aware evaluator, not this speech rubric (ADR 0015/0017). Records
    # without a stage predate the phased Session and are all real questions.
    completed = [r for r in completed if r.get("stage") not in ("intro", "dsa")]
    result = await compiled_graph.ainvoke(
        {
            "session_id": session_id,
            "domain": domain,
            "completed": completed,
            "units": [],
            "scores": [],
            "assessment": "",
            "strengths": [],
            "improvements": [],
            "assessment_retryable": False,
        }
    )
    ordered = sorted(result["scores"], key=lambda s: s["index"])
    answered = sum(1 for s in ordered if not s.get("skipped"))
    retryable_failure = result["assessment_retryable"] or any(
        s.get("retryable") for s in ordered
    )
    return {
        "session_id": session_id,
        "domain": domain,
        "averages": aggregate_scores(ordered),
        "coverage": {"answered": answered, "total": len(ordered)},
        "assessment": result["assessment"],
        "strengths": result["strengths"],
        "improvements": result["improvements"],
        # `index`/`retryable` are internal ordering/caching details, not part
        # of the Candidate-facing Evaluation.
        "questions": [
            {k: v for k, v in s.items() if k not in ("index", "retryable")} for s in ordered
        ],
        "retryable_failure": retryable_failure,
    }
