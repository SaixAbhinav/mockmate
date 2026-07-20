"""Evaluator agent: scores a completed Session against the rubric (ADR 0011).

Where the interviewer graph *branches* (one path per Turn), this one *fans out*:
each completed question is scored by its own concurrent LLM call dispatched with
the Send API — one `score_answer` per spoken question, one `score_submission`
per DSA question — the results are gathered through an `operator.add` reducer
on `scores`, and one call assesses the Session as a whole.

Nodes here return only the keys they change. Spreading the whole state
(`{**state, ...}`) would re-emit `scores` and the reducer would add the list to
itself.
"""

import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from .providers import (
    DIMENSIONS,
    DSA_DIMENSIONS,
    LLMProvider,
    ProviderError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)


class EvaluationState(TypedDict):
    """State for one Session's evaluation pass."""

    session_id: str
    domain: str
    completed: list[dict]
    units: list[dict]
    dsa_units: list[dict]
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


def aggregate_submission_scores(scores: list[dict]) -> dict:
    """The DSA section's aggregate: mean per code Dimension over judged
    entries, plus total Hints used (ADR 0012 names it as a scoring input).

    Facts aggregate over every entry; judgment averages skip unscored and
    skipped ones for the same reason aggregate_scores does.
    """
    judged = [s for s in scores if not s.get("skipped") and not s.get("unscored")]
    if judged:
        averages = {
            dimension: round(sum(s[dimension] for s in judged) / len(judged), 1)
            for dimension in DSA_DIMENSIONS
        }
    else:
        averages = {dimension: None for dimension in DSA_DIMENSIONS}
    return {
        "averages": averages,
        "hints_used": sum(s.get("hints", 0) for s in scores),
    }


def build_evaluator_graph(provider: LLMProvider):
    """Compile the fan-out/gather evaluation graph for the given provider."""

    def plan_evaluation(state: EvaluationState) -> dict:
        units, dsa_units, scores = [], [], []
        for index, record in enumerate(state["completed"]):
            base = {
                "index": index,
                "question": record["question"],
                "topic": record["topic"],
                "difficulty": record["difficulty"],
            }
            if record.get("stage") == "dsa":
                watch = record.get("watch", {})
                dsa_base = {
                    **base,
                    "kind": "dsa",
                    "hints": watch.get("hints", 0),
                    "runs": watch.get("runs", 0),
                }
                if "submission" in record:
                    dsa_units.append(
                        {
                            **dsa_base,
                            "submission": record["submission"],
                            "answers": record["answers"],
                        }
                    )
                else:
                    # Defensive: the Submission is the only way past a coding
                    # question (ADR 0017/0019), so this should be impossible -
                    # but nothing to score must mean no LLM call.
                    scores.append({**dsa_base, "skipped": True})
            elif record["answered"]:
                units.append(
                    {
                        **base,
                        "follow_up_hints": record["follow_up_hints"],
                        "answers": record["answers"],
                    }
                )
            else:
                scores.append({**base, "skipped": True})
        return {"units": units, "dsa_units": dsa_units, "scores": scores}

    def fan_out_to_scorers(state: EvaluationState):
        sends = [Send("score_answer", {"unit": unit}) for unit in state["units"]]
        sends += [Send("score_submission", {"unit": unit}) for unit in state["dsa_units"]]
        return sends or "assess"

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

    async def score_submission(payload: dict) -> dict:
        unit = payload["unit"]
        submission = unit["submission"]
        base = {
            "index": unit["index"],
            "question": unit["question"],
            "topic": unit["topic"],
            "difficulty": unit["difficulty"],
            "kind": "dsa",
            "tests": {
                "status": submission["status"],
                "passed": submission["passed"],
                "total": submission["total"],
            },
            "hints": unit["hints"],
            "runs": unit["runs"],
        }
        try:
            score = await provider.evaluate_submission(
                question=unit["question"],
                code=submission["code"],
                results_summary=(
                    f"status {submission['status']}, "
                    f"passed {submission['passed']} of {submission['total']}"
                ),
                discussion=unit["answers"],
                hints_used=unit["hints"],
                runs=unit["runs"],
            )
            scored = {
                **base,
                "code_quality": score.code_quality,
                "approach": score.approach,
                "comment": score.comment,
            }
        except ProviderError as exc:
            # The judged half fails alone: the entry keeps its test facts.
            # Never logger.exception here - a chained httpx traceback can carry
            # Gemini's API key (ADR 0013).
            logger.warning("could not score submission %r: %s", unit["question"], exc)
            scored = {
                **base,
                "unscored": True,
                "retryable": isinstance(exc, ProviderUnavailableError),
            }
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
    graph.add_node("score_submission", score_submission)
    graph.add_node("assess", assess)

    graph.set_entry_point("plan_evaluation")
    graph.add_conditional_edges(
        "plan_evaluation", fan_out_to_scorers, ["score_answer", "score_submission", "assess"]
    )
    graph.add_edge("score_answer", "assess")
    graph.add_edge("score_submission", "assess")
    graph.add_edge("assess", END)

    return graph.compile()


async def evaluate_session(
    compiled_graph, session_id: str, domain: str, completed: list[dict]
) -> dict:
    """Run the evaluation pass and return the Candidate-facing Evaluation."""
    # The intro is an ice-breaker and is never scored (ADR 0015). DSA records
    # are scored by score_submission since ADR 0020. Records without a stage
    # predate the phased Session and are all real spoken questions.
    completed = [r for r in completed if r.get("stage") != "intro"]
    result = await compiled_graph.ainvoke(
        {
            "session_id": session_id,
            "domain": domain,
            "completed": completed,
            "units": [],
            "dsa_units": [],
            "scores": [],
            "assessment": "",
            "strengths": [],
            "improvements": [],
            "assessment_retryable": False,
        }
    )
    ordered = sorted(result["scores"], key=lambda s: s["index"])
    spoken = [s for s in ordered if s.get("kind") != "dsa"]
    dsa = [s for s in ordered if s.get("kind") == "dsa"]
    answered = sum(1 for s in spoken if not s.get("skipped"))
    retryable_failure = result["assessment_retryable"] or any(
        s.get("retryable") for s in ordered
    )

    def _public(s: dict) -> dict:
        # `index`/`retryable` are internal ordering/caching details and `kind`
        # is the reducer's routing tag - none are part of the Evaluation.
        return {k: v for k, v in s.items() if k not in ("index", "retryable", "kind")}

    return {
        "session_id": session_id,
        "domain": domain,
        "averages": aggregate_scores(spoken),
        "coverage": {"answered": answered, "total": len(spoken)},
        "assessment": result["assessment"],
        "strengths": result["strengths"],
        "improvements": result["improvements"],
        "questions": [_public(s) for s in spoken],
        "dsa": {
            **aggregate_submission_scores(dsa),
            "questions": [_public(s) for s in dsa],
        },
        "retryable_failure": retryable_failure,
    }
