"""Interviewer agent: the state machine that runs one Session (ADR 0006).

`plan_warm_up` and the initial `ask_question` are plain functions
(`start_session`) - they're a straight-line setup with no branching, so a
graph node would add ceremony without value. The actual LangGraph
`StateGraph` covers the part that branches: judging each answer and routing
to probe / clarify / advance / wrap_up. Session state itself lives in the
caller's in-memory dict (ADR 0007), not a LangGraph checkpointer - each HTTP
turn is one `submit_answer` call fed the previous state and returning the
next.
"""

import logging
from dataclasses import asdict
from typing import TypedDict

from langgraph.graph import END, StateGraph

from .providers import LLMProvider, ProviderMalformedError
from .questions import Question, plan_warm_up

logger = logging.getLogger(__name__)

FOLLOW_UP_BUDGET = 2

# The fixed opener for every Session (ADR 0015). Scripted, never paraphrased,
# mirroring ADR 0008's verbatim rule for bank questions. Judged for
# probe/clarify like any question, but excluded from the Evaluation.
INTRO_QUESTION = {
    "domain": "any",
    "topic": "background",
    "difficulty": "easy",
    "question": (
        "To get us started, tell me about yourself - your background and "
        "what you have been working on recently."
    ),
    "follow_up_hints": [
        "Ask for more detail about a project or role they mention",
        "Ask what they enjoyed most or found hardest in that work",
    ],
    "stage": "intro",
}


class InterviewState(TypedDict):
    session_id: str
    domain: str
    queue: list[dict]
    current_question: dict
    follow_up_count: int
    current_answered: bool
    current_answers: list[str]
    completed: list[dict]
    transcript: list[dict[str, str]]
    phase: str
    latest_answer: str
    reply: str
    classification: str


def _question_to_dict(question: Question) -> dict:
    return asdict(question)


def start_session(
    session_id: str,
    domain: str,
    seed: int | None = None,
    warm_up_questions: list[dict] | None = None,
) -> InterviewState:
    """Build a Session: the fixed intro, then the warm-up round (ADR 0015).

    `warm_up_questions` are resume-grounded questions from the provider (the
    ADR 0003 shape minus domain, stamped here). When absent - no resume, no
    key, or generation failed - the warm-up falls back to a curated draw from
    the domain bank. The DSA stage arrives on Day 5 (ADR 0012).
    """
    if warm_up_questions:
        warm_up = [{**q, "domain": domain, "stage": "warm_up"} for q in warm_up_questions]
    else:
        warm_up = [
            {**_question_to_dict(q), "stage": "warm_up"}
            for q in plan_warm_up(domain, seed=seed)
        ]
    queue = [dict(INTRO_QUESTION), *warm_up]
    current = queue.pop(0)
    return InterviewState(
        session_id=session_id,
        domain=domain,
        queue=queue,
        current_question=current,
        follow_up_count=0,
        current_answered=True,
        current_answers=[],
        completed=[],
        transcript=[{"role": "assistant", "content": current["question"]}],
        phase="asking",
        latest_answer="",
        reply=current["question"],
        classification="",
    )


def _close_out_current_question(state: InterviewState) -> list[dict]:
    """Append the current question's result to `completed`.

    Carries what the evaluator agent needs (ADR 0011): the question, its rubric
    anchor (`follow_up_hints`), everything the Candidate said for it, and whether
    it was ever really answered.
    """
    question = state["current_question"]
    record = {
        "question": question["question"],
        "topic": question["topic"],
        "difficulty": question["difficulty"],
        "stage": question["stage"],
        "follow_up_hints": question["follow_up_hints"],
        "answers": list(state["current_answers"]),
        "answered": state["current_answered"],
    }
    return [*state["completed"], record]


def build_graph(provider: LLMProvider):
    async def judge_answer_depth(state: InterviewState) -> InterviewState:
        classification = "advance"
        reply = "Thanks, let's move on."
        answered = state["current_answered"]
        try:
            judgment = await provider.judge_answer(
                question=state["current_question"]["question"],
                follow_up_hints=state["current_question"]["follow_up_hints"],
                history=state["transcript"],
                answer=state["latest_answer"],
            )
            if judgment.classification in ("probe", "clarify", "advance"):
                classification = judgment.classification
                reply = judgment.reply
                answered = judgment.answered
            else:
                logger.warning(
                    "unknown judge classification %r, defaulting to advance",
                    judgment.classification,
                )
        except ProviderMalformedError as exc:
            logger.warning("malformed judge response, defaulting to advance: %s", exc)

        return {
            **state,
            "classification": classification,
            "reply": reply,
            "current_answered": answered,
            "current_answers": [*state["current_answers"], state["latest_answer"]],
        }

    def route_after_judgment(state: InterviewState) -> str:
        if state["classification"] in ("probe", "clarify"):
            if state["follow_up_count"] >= FOLLOW_UP_BUDGET:
                return "advance"  # budget exhausted, force advance
            return state["classification"]
        return "advance"

    def _append_turn(state: InterviewState) -> list[dict[str, str]]:
        return [
            *state["transcript"],
            {"role": "user", "content": state["latest_answer"]},
            {"role": "assistant", "content": state["reply"]},
        ]

    def probe(state: InterviewState) -> InterviewState:
        return {
            **state,
            "transcript": _append_turn(state),
            "follow_up_count": state["follow_up_count"] + 1,
            "phase": "probing",
        }

    def clarify(state: InterviewState) -> InterviewState:
        return {
            **state,
            "transcript": _append_turn(state),
            "follow_up_count": state["follow_up_count"] + 1,
            "phase": "clarifying",
        }

    def advance(state: InterviewState) -> InterviewState:
        forced = (
            state["classification"] in ("probe", "clarify")
            and state["follow_up_count"] >= FOLLOW_UP_BUDGET
        )
        if forced:
            # The judge's reply is a follow-up question we can no longer ask —
            # discard it for a neutral transition. Clarify exhaustion means the
            # candidate never truly answered; probe exhaustion is shallow-but-
            # answered (ADR 0006).
            state = {
                **state,
                "reply": "Alright, let's move on.",
                "current_answered": state["classification"] == "probe",
            }
        return {
            **state,
            "transcript": _append_turn(state),
            "phase": "advancing",
        }

    def route_after_advance(state: InterviewState) -> str:
        return "wrap_up" if not state["queue"] else "next_question"

    def next_question(state: InterviewState) -> InterviewState:
        completed = _close_out_current_question(state)
        queue = list(state["queue"])
        nxt = queue.pop(0)
        transcript = [*state["transcript"], {"role": "assistant", "content": nxt["question"]}]
        return {
            **state,
            "completed": completed,
            "queue": queue,
            "current_question": nxt,
            "follow_up_count": 0,
            "current_answered": True,
            "current_answers": [],
            "transcript": transcript,
            "reply": f"{state['reply']} {nxt['question']}",
            "phase": "asking",
        }

    async def wrap_up(state: InterviewState) -> InterviewState:
        completed = _close_out_current_question(state)
        closing = await provider.wrap_up(state["transcript"])
        transcript = [*state["transcript"], {"role": "assistant", "content": closing}]
        return {
            **state,
            "completed": completed,
            "transcript": transcript,
            "reply": closing,
            "phase": "done",
        }

    graph = StateGraph(InterviewState)
    graph.add_node("judge_answer_depth", judge_answer_depth)
    graph.add_node("probe", probe)
    graph.add_node("clarify", clarify)
    graph.add_node("advance", advance)
    graph.add_node("next_question", next_question)
    graph.add_node("wrap_up", wrap_up)

    graph.set_entry_point("judge_answer_depth")
    graph.add_conditional_edges(
        "judge_answer_depth",
        route_after_judgment,
        {"probe": "probe", "clarify": "clarify", "advance": "advance"},
    )
    graph.add_edge("probe", END)
    graph.add_edge("clarify", END)
    graph.add_conditional_edges(
        "advance",
        route_after_advance,
        {"next_question": "next_question", "wrap_up": "wrap_up"},
    )
    graph.add_edge("next_question", END)
    graph.add_edge("wrap_up", END)

    return graph.compile()


async def submit_answer(compiled_graph, state: InterviewState, answer: str) -> InterviewState:
    return await compiled_graph.ainvoke({**state, "latest_answer": answer})
