"""Interviewer agent: the state machine that runs one Session (ADR 0006).

`plan_session` and the initial `ask_question` are plain functions
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

from .providers import LLMProvider, ProviderError
from .questions import Question, plan_session

logger = logging.getLogger(__name__)

FOLLOW_UP_BUDGET = 2


class InterviewState(TypedDict):
    session_id: str
    domain: str
    queue: list[dict]
    current_question: dict
    follow_up_count: int
    current_answered: bool
    completed: list[dict]
    transcript: list[dict[str, str]]
    phase: str
    latest_answer: str
    reply: str
    classification: str


def _question_to_dict(question: Question) -> dict:
    return asdict(question)


def start_session(session_id: str, domain: str, seed: int | None = None) -> InterviewState:
    queue = [_question_to_dict(q) for q in plan_session(domain, seed=seed)]
    current = queue.pop(0)
    return InterviewState(
        session_id=session_id,
        domain=domain,
        queue=queue,
        current_question=current,
        follow_up_count=0,
        current_answered=True,
        completed=[],
        transcript=[{"role": "assistant", "content": current["question"]}],
        phase="asking",
        latest_answer="",
        reply=current["question"],
        classification="",
    )


def _close_out_current_question(state: InterviewState) -> list[dict]:
    record = {
        "question": state["current_question"]["question"],
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
        except ProviderError as exc:
            logger.warning("malformed judge response, defaulting to advance: %s", exc)

        return {**state, "classification": classification, "reply": reply, "current_answered": answered}

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
        budget_exhausted_unresolved = (
            state["classification"] in ("probe", "clarify")
            and state["follow_up_count"] >= FOLLOW_UP_BUDGET
        )
        return {
            **state,
            "transcript": _append_turn(state),
            "current_answered": False if budget_exhausted_unresolved else state["current_answered"],
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
