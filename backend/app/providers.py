"""LLM providers behind one interface (ADR 0002, ADR 0006).

The interviewer agent only ever calls `get_provider().judge_answer(...)` and
`.wrap_up(...)`. Which model answers - Groq, Gemini, or the scripted
fallback - is a deployment detail decided by environment variables, never by
application code.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from .questions import DIFFICULTIES

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = (
    "You are a professional but friendly technical interviewer running a mock "
    "interview. You are given the current question, hints for good follow-ups, "
    "the conversation so far, and the candidate's latest answer. Decide one of "
    "three classifications: 'probe' (answer is on-topic but shallow/incomplete - "
    "ask a same-topic follow-up), 'clarify' (answer is off-topic or shows a "
    "misunderstanding - ask a clarifying follow-up), or 'advance' (answer is "
    "good enough - move on). Ground probe/clarify follow-ups in the hints, but "
    "don't read them verbatim. On 'advance', reply is only a one-sentence "
    "reaction (the next question is appended separately, never by you). Keep "
    "replies under 60 words - they are spoken aloud. Respond with strict JSON "
    'only: {"classification": "probe"|"clarify"|"advance", "reply": string, '
    '"answered": boolean}. "answered" is false only if the candidate has not '
    "yet given a real answer to the question."
)

WRAP_UP_SYSTEM_PROMPT = (
    "The mock interview is complete. Write a brief, warm one or two sentence "
    "closing remark for the candidate based on the transcript. Do not score, "
    "grade, or critique the answers - that is a separate step. Do not address "
    "the candidate by name - you do not know it. Keep it under 40 words; it is "
    "spoken aloud."
)

EVALUATE_SYSTEM_PROMPT = (
    "You are evaluating one answer from a completed mock technical interview. "
    "You are given the question, a list of hints, and everything the candidate "
    "said for that question (their first answer plus any follow-up responses).\n"
    "The hints are notes written for the interviewer, phrased as instructions "
    "like 'Ask about X'. They tell you which topics a strong answer would touch "
    "on. Judge whether the candidate covered the underlying topic. Never reward "
    "or penalise the candidate for asking anything — asking is the interviewer's "
    "job, not theirs. The hints are not exhaustive: an answer can be excellent "
    "without matching them.\n"
    "Score the answer on three dimensions, each an integer from 1 to 5: "
    "'correctness' (is what they said accurate?), 'depth' (did they go beyond "
    "the surface?), and 'clarity' (was it organised and easy to follow as "
    "speech?). Also write one sentence of specific, actionable feedback. Do not "
    "be generous: 3 means adequate, 5 means excellent. Respond with strict JSON "
    'only: {"correctness": int, "depth": int, "clarity": int, "comment": string}.'
)

ASSESS_SYSTEM_PROMPT = (
    "You are assessing a completed mock technical interview for the candidate. "
    "You are given the per-question scores and comments. Write a brief overall "
    "assessment of two or three sentences, then list key strengths and areas to "
    "work on. Be specific and reference what they actually said. Give at most 3 "
    "strengths and at most 3 improvements. Respond with strict JSON only: "
    '{"assessment": string, "strengths": [string], "improvements": [string]}.'
)

EVALUATE_SUBMISSION_SYSTEM_PROMPT = (
    "You are evaluating the coding round of a completed mock technical "
    "interview. You are given the coding question, the candidate's submitted "
    "Python code, the objective test results, everything they said in the "
    "discussion after submitting, and how many hints the interviewer gave and "
    "how many times they ran the tests while working. Correctness is already "
    "measured by the tests — do not re-judge whether the code passes. Score "
    "two dimensions, each an integer from 1 to 5: 'code_quality' (readable, "
    "idiomatic Python that handles edge cases) and 'approach' (a sound "
    "algorithm for the problem, and how well the candidate explained and "
    "defended it in the discussion). Hint and run counts are context about "
    "how independently they worked — weigh them with judgment, never as a "
    "mechanical penalty. Also write one sentence of specific, actionable "
    "feedback about the code itself. Do not be generous: 3 means adequate, "
    "5 means excellent. Respond with strict JSON only: "
    '{"code_quality": int, "approach": int, "comment": string}.'
)

WARM_UP_QUESTIONS_SYSTEM_PROMPT = (
    "You are preparing the warm-up round of a mock technical interview. You "
    "are given the candidate's resume text. Write exactly 3 short spoken "
    "interview questions about the candidate's own background - their "
    "projects, skills, and experience - in whatever field the resume actually "
    "shows. Every question must be answerable from what the resume actually "
    "says: never invent projects, employers, or skills that are not on it. "
    "Also report 'domain': two or three words naming that field the way a "
    "person would say it, for example 'web development', 'machine learning', "
    "or 'embedded systems'. For each question also write: 'topic' (one or two "
    "words), 'difficulty' (one of easy, medium, hard), and 'follow_up_hints' "
    "- 2 instructions to the interviewer for probing deeper, phrased like "
    "'Ask about X'. Keep each question under 30 words - it is spoken aloud. "
    'Respond with strict JSON only: {"domain": string, "questions": '
    '[{"topic": string, "difficulty": "easy"|"medium"|"hard", '
    '"question": string, "follow_up_hints": [string]}]}.'
)

REACT_TO_CODE_SYSTEM_PROMPT = (
    "You are a professional but friendly technical interviewer in the live "
    "coding round of a mock interview. You are given the coding question, the "
    "candidate's submitted Python code, and the results of running it against "
    "the test cases. You also see the conversation so far, including anything "
    "you said while watching them code: if the candidate followed a hint you "
    "gave, acknowledge it naturally - never ask them to justify choosing an "
    "approach you suggested. Reply with one short spoken remark: one sentence "
    "that honestly acknowledges the result (all passing, partially passing, "
    "failing, crashed, or timed out), then exactly one question about their "
    "approach - why they chose it, its complexity, or how they would fix a "
    "failing case. Never dictate the corrected solution. Keep it under 60 "
    "words - it is spoken aloud. Respond with plain text, not JSON."
)

WATCH_CODE_SYSTEM_PROMPT = (
    "You are a professional but friendly technical interviewer watching a "
    "candidate write Python during the live coding round of a mock "
    "interview. You are given the coding question, the candidate's current "
    "code (a work in progress, not a submission), how long they have been "
    "on this question, whether they appear stuck (no meaningful edits "
    "since your last look), and a summary of their test runs so far. "
    "Decide one of three actions: 'silent' (the default - a candidate "
    "making progress should be left alone), 'ask' (one short question "
    "about what they are doing, only when something notable is on screen), "
    "or 'hint' (only when they are stuck or repeatedly failing the tests - "
    "one small nudge toward the next step, never the solution or its "
    "code). Keep the remark under 40 words - it is spoken aloud; use an "
    "empty string when silent. Respond with strict JSON only: "
    '{"action": "silent"|"ask"|"hint", "remark": string}.'
)

CODING_CHAT_SYSTEM_PROMPT = (
    "You are a professional but friendly technical interviewer in the live "
    "coding round of a mock interview. The candidate is still writing code "
    "and just said something aloud. You are given the coding question, "
    "their current code, and what they said. Reply with one short spoken "
    "response: answer a clarifying question about the problem, acknowledge "
    "thinking aloud, or nudge them to keep going. Never dictate the "
    "solution or write code for them; if they ask for the answer, decline "
    "warmly and offer a direction instead. Keep it under 40 words - it is "
    "spoken aloud. Respond with plain text, not JSON."
)

WATCH_ACTIONS = ("silent", "ask", "hint")

DIMENSIONS = ("correctness", "depth", "clarity")

DSA_DIMENSIONS = ("code_quality", "approach")


class ProviderError(Exception):
    """Base: the provider could not give a usable answer."""


class ProviderMalformedError(ProviderError):
    """The provider replied, but the reply could not be parsed."""


class ProviderUnavailableError(ProviderError):
    """The provider could not be reached — transport failure, rate limit, timeout."""


@dataclass(frozen=True)
class Judgment:
    classification: str
    reply: str
    answered: bool


@dataclass(frozen=True)
class AnswerScore:
    """One question's Score: its three Dimensions plus a one-sentence comment."""

    correctness: int
    depth: int
    clarity: int
    comment: str


@dataclass(frozen=True)
class SubmissionScore:
    """The judged half of one DSA question's Score (ADR 0020).

    Correctness is not here on purpose: it comes from the Runner's test
    results, which the model is told not to re-judge.
    """

    code_quality: int
    approach: int
    comment: str


MAX_DOMAIN_LABEL_CHARS = 60


@dataclass(frozen=True)
class WarmUp:
    """Resume-grounded warm-up questions plus the field the resume shows
    (ADR 0023).

    `domain` is a display label: it selects nothing, it describes the Session.
    Empty `questions` means the provider cannot generate them and the caller
    should fall back to the curated bank (ADR 0015).
    """

    domain: str
    questions: list[dict]


@dataclass(frozen=True)
class Assessment:
    """The prose half of an Evaluation: overall read, strengths, improvements."""

    assessment: str
    strengths: list[str]
    improvements: list[str]


@dataclass(frozen=True)
class WatchDecision:
    """The watching interviewer's call on one Check-in (ADR 0018)."""

    action: str  # "silent" | "ask" | "hint"
    remark: str


class LLMProvider(Protocol):
    name: str

    async def judge_answer(
        self,
        question: str,
        follow_up_hints: list[str],
        history: list[dict[str, str]],
        answer: str,
    ) -> Judgment:
        """history is prior {"role": "user"|"assistant", "content": str} turns."""
        ...

    async def wrap_up(self, transcript: list[dict[str, str]]) -> str:
        """Returns a closing remark; no scoring."""
        ...

    async def evaluate_answer(
        self, question: str, follow_up_hints: list[str], answers: list[str]
    ) -> AnswerScore:
        """Score one completed question's exchange. Raises ProviderError on failure."""
        ...

    async def assess_session(self, scores: list[dict]) -> Assessment:
        """Overall assessment from per-question Scores. Raises ProviderError on failure."""
        ...

    async def evaluate_submission(
        self, question: str, code: str, results_summary: str,
        discussion: list[str], hints_used: int, runs: int,
    ) -> SubmissionScore:
        """Judge one DSA Submission's code quality and approach (ADR 0020).
        Correctness comes from the test results, not from this call.
        Raises ProviderError on failure — the caller marks the entry unscored."""
        ...

    async def generate_warm_up_questions(self, resume_text: str) -> WarmUp:
        """Resume-grounded warm-up questions plus the inferred field (ADR 0015,
        ADR 0023), questions in the ADR 0003 shape (minus domain). Empty
        `questions` means the provider cannot generate them.
        Raises ProviderError on failure."""
        ...

    async def react_to_code(
        self, question: str, code: str, results_summary: str,
        history: list[dict[str, str]],
    ) -> str:
        """Spoken reaction to a DSA submission plus one approach question
        (ADR 0017/0019). Sees the transcript so it never contradicts the
        watcher's own hints. Plain text. Raises ProviderError on failure."""
        ...

    async def watch_code(
        self, question: str, code: str, stuck: bool, seconds_elapsed: float,
        runs_summary: str,
    ) -> WatchDecision:
        """One Check-in on the Candidate's work in progress (ADR 0018).
        Raises ProviderError on failure - the caller stays silent."""
        ...

    async def coding_chat(
        self, question: str, code: str, history: list[dict[str, str]], utterance: str
    ) -> str:
        """Spoken reply to a Candidate talking while coding (ADR 0019).
        Plain text; never advances the interview. Raises ProviderError."""
        ...


def _judge_user_turn(question: str, follow_up_hints: list[str], answer: str) -> str:
    return (
        f"Current question: {question}\n"
        f"Follow-up hints: {follow_up_hints}\n"
        f"Candidate's latest answer: {answer}"
    )


def _parse_judgment(content: str) -> Judgment:
    try:
        data = json.loads(content)
        return Judgment(
            classification=data["classification"],
            reply=data["reply"],
            answered=bool(data["answered"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProviderMalformedError(f"malformed judge response: {content!r}") from exc


def _evaluate_user_turn(question: str, follow_up_hints: list[str], answers: list[str]) -> str:
    said = "\n".join(f"- {a}" for a in answers)
    return (
        f"Question: {question}\n"
        f"Interviewer hints (topics a strong answer touches): {follow_up_hints}\n"
        f"Everything the candidate said for this question:\n{said}"
    )


def _evaluate_submission_user_turn(
    question: str, code: str, results_summary: str,
    discussion: list[str], hints_used: int, runs: int,
) -> str:
    said = "\n".join(f"- {a}" for a in discussion) or "- (nothing)"
    return (
        f"Coding question: {question}\n"
        f"Submitted code:\n{code}\n"
        f"Test results: {results_summary}\n"
        f"Hints given while coding: {hints_used}; test runs while coding: {runs}\n"
        f"What the candidate said in the discussion:\n{said}"
    )


def _assess_user_turn(scores: list[dict]) -> str:
    lines = []
    for s in scores:
        if s.get("kind") == "dsa":
            lines.append(_assess_coding_line(s))
        elif s.get("skipped"):
            lines.append(f"- {s['question']}: never answered")
        elif s.get("unscored") or not all(k in s for k in (*DIMENSIONS, "comment")):
            lines.append(f"- {s['question']}: could not be scored")
        else:
            lines.append(
                f"- {s['question']}: correctness {s['correctness']}, "
                f"depth {s['depth']}, clarity {s['clarity']} — {s['comment']}"
            )
    return "Per-question results:\n" + "\n".join(lines)


def _assess_coding_line(s: dict) -> str:
    """One DSA entry for the assessment prompt: facts first, judgment second."""
    tests = s.get("tests")
    outcome = (
        f"tests {tests['status']}, passed {tests['passed']} of {tests['total']}"
        if tests
        else "never submitted"
    )
    if not all(k in s for k in (*DSA_DIMENSIONS, "comment")):
        return f"- {s['question']} (coding): {outcome}; the code itself could not be scored"
    return (
        f"- {s['question']} (coding): {outcome}; code quality {s['code_quality']}, "
        f"approach {s['approach']}, {s.get('hints', 0)} hint(s) used — {s['comment']}"
    )


def _warm_up_user_turn(resume_text: str) -> str:
    return f"Resume:\n{resume_text}"


def _react_user_turn(question: str, code: str, results_summary: str) -> str:
    return (
        f"Coding question: {question}\n"
        f"Submitted code:\n{code}\n"
        f"Test results: {results_summary}"
    )


def _watch_user_turn(
    question: str, code: str, stuck: bool, seconds_elapsed: float, runs_summary: str
) -> str:
    progress = (
        "no meaningful edits since your last look" if stuck else "actively editing"
    )
    return (
        f"Coding question: {question}\n"
        f"Current code (work in progress):\n{code}\n"
        f"Time on this question: {int(seconds_elapsed)} seconds\n"
        f"Progress: {progress}\n"
        f"Test runs: {runs_summary}"
    )


def _coding_chat_user_turn(question: str, code: str, utterance: str) -> str:
    return (
        f"Coding question: {question}\n"
        f"Current code (work in progress):\n{code}\n"
        f"The candidate just said: {utterance}"
    )


def _parse_watch_decision(content: str) -> WatchDecision:
    try:
        data = json.loads(content)
        action = data["action"]
        remark = data["remark"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProviderMalformedError(f"malformed watch decision: {content!r}") from exc
    if action not in WATCH_ACTIONS:
        raise ProviderMalformedError(f"unknown watch action: {action!r}")
    if not isinstance(remark, str):
        raise ProviderMalformedError(f"watch remark must be a string: {remark!r}")
    if action != "silent" and not remark.strip():
        raise ProviderMalformedError(f"watch action {action!r} needs a remark")
    return WatchDecision(action=action, remark=remark)


def _parse_warm_up_questions(content: str) -> WarmUp:
    try:
        data = json.loads(content)
        domain = data["domain"]
        questions = [
            {
                "topic": entry["topic"],
                "difficulty": entry["difficulty"],
                "question": entry["question"],
                "follow_up_hints": list(entry["follow_up_hints"]),
            }
            for entry in data["questions"]
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProviderMalformedError(
            f"malformed warm-up questions response: {content!r}"
        ) from exc
    if not isinstance(domain, str) or not domain.strip():
        raise ProviderMalformedError(f"bad warm-up domain: {domain!r}")
    # The label is displayed, never matched against anything (ADR 0023), so a
    # rambling answer is cosmetic - truncate rather than fail the whole Session.
    domain = domain.strip()[:MAX_DOMAIN_LABEL_CHARS]
    if not 2 <= len(questions) <= 4:
        raise ProviderMalformedError(
            f"expected 2-4 warm-up questions, got {len(questions)}"
        )
    for q in questions:
        if q["difficulty"] not in DIFFICULTIES:
            raise ProviderMalformedError(f"bad warm-up difficulty: {q['difficulty']!r}")
        if not q["follow_up_hints"]:
            raise ProviderMalformedError("warm-up follow_up_hints must be non-empty")
    return WarmUp(domain=domain, questions=questions)


def _parse_score(content: str) -> AnswerScore:
    try:
        data = json.loads(content)
        values = {d: int(data[d]) for d in DIMENSIONS}
        comment = data["comment"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderMalformedError(f"malformed score response: {content!r}") from exc
    for dimension, value in values.items():
        if not 1 <= value <= 5:
            raise ProviderMalformedError(f"{dimension} out of range 1-5: {value}")
    if not isinstance(comment, str):
        raise ProviderMalformedError(f"comment must be a string: {comment!r}")
    return AnswerScore(**values, comment=comment)


def _parse_submission_score(content: str) -> SubmissionScore:
    try:
        data = json.loads(content)
        values = {d: int(data[d]) for d in DSA_DIMENSIONS}
        comment = data["comment"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderMalformedError(f"malformed submission score: {content!r}") from exc
    for dimension, value in values.items():
        if not 1 <= value <= 5:
            raise ProviderMalformedError(f"{dimension} out of range 1-5: {value}")
    if not isinstance(comment, str):
        raise ProviderMalformedError(f"comment must be a string: {comment!r}")
    return SubmissionScore(**values, comment=comment)


def _parse_assessment(content: str) -> Assessment:
    try:
        data = json.loads(content)
        return Assessment(
            assessment=data["assessment"],
            strengths=list(data["strengths"]),
            improvements=list(data["improvements"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProviderMalformedError(f"malformed assessment response: {content!r}") from exc


class GroqProvider:
    """Groq's OpenAI-compatible endpoint. Free tier, 70B-class models."""

    name = "groq"
    _url = "https://api.groq.com/openai/v1/chat/completions"
    _model = "llama-3.3-70b-versatile"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def judge_answer(
        self,
        question: str,
        follow_up_hints: list[str],
        history: list[dict[str, str]],
        answer: str,
    ) -> Judgment:
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": _judge_user_turn(question, follow_up_hints, answer)},
        ]
        content = await self._chat_json(messages, max_tokens=300)
        return _parse_judgment(content)

    async def wrap_up(self, transcript: list[dict[str, str]]) -> str:
        messages = [{"role": "system", "content": WRAP_UP_SYSTEM_PROMPT}, *transcript]
        return await self._chat_json(messages, max_tokens=150, json_mode=False)

    async def evaluate_answer(
        self, question: str, follow_up_hints: list[str], answers: list[str]
    ) -> AnswerScore:
        messages = [
            {"role": "system", "content": EVALUATE_SYSTEM_PROMPT},
            {"role": "user", "content": _evaluate_user_turn(question, follow_up_hints, answers)},
        ]
        return _parse_score(await self._chat_json(messages, max_tokens=300))

    async def assess_session(self, scores: list[dict]) -> Assessment:
        messages = [
            {"role": "system", "content": ASSESS_SYSTEM_PROMPT},
            {"role": "user", "content": _assess_user_turn(scores)},
        ]
        return _parse_assessment(await self._chat_json(messages, max_tokens=500))

    async def evaluate_submission(
        self, question: str, code: str, results_summary: str,
        discussion: list[str], hints_used: int, runs: int,
    ) -> SubmissionScore:
        messages = [
            {"role": "system", "content": EVALUATE_SUBMISSION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _evaluate_submission_user_turn(
                    question, code, results_summary, discussion, hints_used, runs
                ),
            },
        ]
        return _parse_submission_score(await self._chat_json(messages, max_tokens=300))

    async def generate_warm_up_questions(self, resume_text: str) -> WarmUp:
        messages = [
            {"role": "system", "content": WARM_UP_QUESTIONS_SYSTEM_PROMPT},
            {"role": "user", "content": _warm_up_user_turn(resume_text)},
        ]
        return _parse_warm_up_questions(await self._chat_json(messages, max_tokens=800))

    async def react_to_code(
        self, question: str, code: str, results_summary: str,
        history: list[dict[str, str]],
    ) -> str:
        messages = [
            {"role": "system", "content": REACT_TO_CODE_SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": _react_user_turn(question, code, results_summary)},
        ]
        return await self._chat_json(messages, max_tokens=200, json_mode=False)

    async def watch_code(
        self, question: str, code: str, stuck: bool, seconds_elapsed: float,
        runs_summary: str,
    ) -> WatchDecision:
        messages = [
            {"role": "system", "content": WATCH_CODE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _watch_user_turn(
                    question, code, stuck, seconds_elapsed, runs_summary
                ),
            },
        ]
        return _parse_watch_decision(await self._chat_json(messages, max_tokens=150))

    async def coding_chat(
        self, question: str, code: str, history: list[dict[str, str]], utterance: str
    ) -> str:
        messages = [
            {"role": "system", "content": CODING_CHAT_SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": _coding_chat_user_turn(question, code, utterance)},
        ]
        return await self._chat_json(messages, max_tokens=150, json_mode=False)

    async def _chat_json(
        self, messages: list[dict[str, str]], max_tokens: int, json_mode: bool = True
    ) -> str:
        payload = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"groq request failed: {exc}") from exc
        except ValueError as exc:  # includes json.JSONDecodeError
            raise ProviderMalformedError(f"groq returned a non-JSON body: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderMalformedError(f"unexpected groq response shape: {body!r}") from exc


class GeminiProvider:
    """Google Gemini REST API. Free tier."""

    name = "gemini"
    _model = "gemini-2.0-flash"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def judge_answer(
        self,
        question: str,
        follow_up_hints: list[str],
        history: list[dict[str, str]],
        answer: str,
    ) -> Judgment:
        contents = self._to_gemini_contents(history)
        contents.append(
            {"role": "user", "parts": [{"text": _judge_user_turn(question, follow_up_hints, answer)}]}
        )
        content = await self._generate(
            JUDGE_SYSTEM_PROMPT, contents, response_mime_type="application/json"
        )
        return _parse_judgment(content)

    async def wrap_up(self, transcript: list[dict[str, str]]) -> str:
        contents = self._to_gemini_contents(transcript)
        return await self._generate(WRAP_UP_SYSTEM_PROMPT, contents)

    async def evaluate_answer(
        self, question: str, follow_up_hints: list[str], answers: list[str]
    ) -> AnswerScore:
        contents = [
            {
                "role": "user",
                "parts": [{"text": _evaluate_user_turn(question, follow_up_hints, answers)}],
            }
        ]
        content = await self._generate(
            EVALUATE_SYSTEM_PROMPT, contents, response_mime_type="application/json"
        )
        return _parse_score(content)

    async def assess_session(self, scores: list[dict]) -> Assessment:
        contents = [{"role": "user", "parts": [{"text": _assess_user_turn(scores)}]}]
        content = await self._generate(
            ASSESS_SYSTEM_PROMPT, contents, response_mime_type="application/json"
        )
        return _parse_assessment(content)

    async def evaluate_submission(
        self, question: str, code: str, results_summary: str,
        discussion: list[str], hints_used: int, runs: int,
    ) -> SubmissionScore:
        contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": _evaluate_submission_user_turn(
                            question, code, results_summary, discussion, hints_used, runs
                        )
                    }
                ],
            }
        ]
        content = await self._generate(
            EVALUATE_SUBMISSION_SYSTEM_PROMPT, contents,
            response_mime_type="application/json",
        )
        return _parse_submission_score(content)

    async def generate_warm_up_questions(self, resume_text: str) -> WarmUp:
        contents = [
            {"role": "user", "parts": [{"text": _warm_up_user_turn(resume_text)}]}
        ]
        content = await self._generate(
            WARM_UP_QUESTIONS_SYSTEM_PROMPT, contents, response_mime_type="application/json"
        )
        return _parse_warm_up_questions(content)

    async def react_to_code(
        self, question: str, code: str, results_summary: str,
        history: list[dict[str, str]],
    ) -> str:
        contents = self._to_gemini_contents(history)
        contents.append(
            {"role": "user", "parts": [{"text": _react_user_turn(question, code, results_summary)}]}
        )
        return await self._generate(REACT_TO_CODE_SYSTEM_PROMPT, contents)

    async def watch_code(
        self, question: str, code: str, stuck: bool, seconds_elapsed: float,
        runs_summary: str,
    ) -> WatchDecision:
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": _watch_user_turn(question, code, stuck, seconds_elapsed, runs_summary)}
                ],
            }
        ]
        content = await self._generate(
            WATCH_CODE_SYSTEM_PROMPT, contents, response_mime_type="application/json"
        )
        return _parse_watch_decision(content)

    async def coding_chat(
        self, question: str, code: str, history: list[dict[str, str]], utterance: str
    ) -> str:
        contents = self._to_gemini_contents(history)
        contents.append(
            {
                "role": "user",
                "parts": [{"text": _coding_chat_user_turn(question, code, utterance)}],
            }
        )
        return await self._generate(CODING_CHAT_SYSTEM_PROMPT, contents)

    @staticmethod
    def _to_gemini_contents(history: list[dict[str, str]]) -> list[dict]:
        return [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"text": m["content"]}]}
            for m in history
        ]

    async def _generate(
        self, system_prompt: str, contents: list[dict], response_mime_type: str | None = None
    ) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        generation_config = {}
        if response_mime_type:
            generation_config["response_mime_type"] = response_mime_type
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
        }
        if generation_config:
            payload["generationConfig"] = generation_config
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            # Never interpolate str(exc): the URL carries the API key.
            raise ProviderUnavailableError(
                f"gemini returned {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"gemini request failed: {type(exc).__name__}"
            ) from exc
        except ValueError as exc:
            raise ProviderMalformedError("gemini returned a non-JSON body") from exc

        try:
            return body["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderMalformedError(f"unexpected gemini response shape: {body!r}") from exc


class ScriptedProvider:
    """No-key fallback so the interview graph is testable without any account.

    Walks through the queue: always advances, never probes or clarifies
    (ADR 0006). Also doubles as the test fake for graph tests.
    """

    name = "scripted"

    async def judge_answer(
        self,
        question: str,
        follow_up_hints: list[str],
        history: list[dict[str, str]],
        answer: str,
    ) -> Judgment:
        return Judgment(classification="advance", reply="Thanks, noted.", answered=True)

    async def wrap_up(self, transcript: list[dict[str, str]]) -> str:
        return (
            "That's the end of the scripted demo. Add a GROQ_API_KEY or "
            "GEMINI_API_KEY to backend slash dot env to unlock a real interviewer."
        )

    async def evaluate_answer(
        self, question: str, follow_up_hints: list[str], answers: list[str]
    ) -> AnswerScore:
        return AnswerScore(
            correctness=3,
            depth=3,
            clarity=3,
            comment="Scripted demo score — add an API key for a real evaluation.",
        )

    async def assess_session(self, scores: list[dict]) -> Assessment:
        return Assessment(
            assessment=(
                "That's the end of the scripted demo. Add a GROQ_API_KEY or "
                "GEMINI_API_KEY to backend slash dot env to unlock real scoring."
            ),
            strengths=["Completed the interview"],
            improvements=["Add an API key to get real feedback"],
        )

    async def evaluate_submission(
        self, question: str, code: str, results_summary: str,
        discussion: list[str], hints_used: int, runs: int,
    ) -> SubmissionScore:
        # The judgment is canned, but the entry's test facts are real — the
        # keyless demo shows genuine pass/fail (ADR 0020).
        return SubmissionScore(
            code_quality=3,
            approach=3,
            comment="Scripted demo score — add an API key for a real code review.",
        )

    async def generate_warm_up_questions(self, resume_text: str) -> WarmUp:
        # No model, no generation - the endpoint falls back to the curated bank.
        return WarmUp(domain="", questions=[])

    async def react_to_code(
        self, question: str, code: str, results_summary: str,
        history: list[dict[str, str]],
    ) -> str:
        return (
            "Thanks for submitting. Talk me through your approach - what does "
            "your solution do, and what is its time complexity?"
        )

    async def watch_code(
        self, question: str, code: str, stuck: bool, seconds_elapsed: float,
        runs_summary: str,
    ) -> WatchDecision:
        # No model, no opinion: the scripted watcher never interrupts. The
        # deterministic Offer (ADR 0018) is the keyless demo's one watching
        # behavior; canned LLM-style interjections would just nag.
        return WatchDecision(action="silent", remark="")

    async def coding_chat(
        self, question: str, code: str, history: list[dict[str, str]], utterance: str
    ) -> str:
        return (
            "I'm listening - keep going. If you're stuck, run the tests and "
            "talk me through what you're seeing."
        )


class FailoverProvider:
    """Two providers, two quotas: retry on the secondary when the primary is
    unreachable (ADR 0014).

    Only ProviderUnavailableError triggers failover. A malformed reply is a
    deterministic parsing failure, not an outage — retrying it on a different
    model would mask real bugs, and each caller already has its own
    malformed-reply recovery (ADR 0013).
    """

    def __init__(self, primary: LLMProvider, secondary: LLMProvider):
        self._primary = primary
        self._secondary = secondary
        self.name = f"{primary.name}+{secondary.name}"

    async def _call(self, method: str, **kwargs):
        # `ok` is on the log line because a failed call would otherwise read
        # exactly like a slow successful one and skew the latency picture the
        # timing exists to give. On the failover path the elapsed time spans
        # both providers, which is the number the Candidate actually waited.
        started = time.perf_counter()
        ok = False
        try:
            try:
                result = await getattr(self._primary, method)(**kwargs)
            except ProviderUnavailableError as exc:
                # Log the provider's own message only — never the chained
                # traceback (Gemini's key rides in its request URL, ADR 0013).
                logger.warning(
                    "%s unavailable, failing over to %s: %s",
                    self._primary.name,
                    self._secondary.name,
                    exc,
                )
                result = await getattr(self._secondary, method)(**kwargs)
            ok = True  # only reached when no exception escaped
            return result
        finally:
            logger.info(
                "llm call op=%s ok=%s ms=%.0f",
                method,
                ok,
                (time.perf_counter() - started) * 1000,
            )

    async def judge_answer(
        self,
        question: str,
        follow_up_hints: list[str],
        history: list[dict[str, str]],
        answer: str,
    ) -> Judgment:
        return await self._call(
            "judge_answer",
            question=question,
            follow_up_hints=follow_up_hints,
            history=history,
            answer=answer,
        )

    async def wrap_up(self, transcript: list[dict[str, str]]) -> str:
        return await self._call("wrap_up", transcript=transcript)

    async def evaluate_answer(
        self, question: str, follow_up_hints: list[str], answers: list[str]
    ) -> AnswerScore:
        return await self._call(
            "evaluate_answer",
            question=question,
            follow_up_hints=follow_up_hints,
            answers=answers,
        )

    async def assess_session(self, scores: list[dict]) -> Assessment:
        return await self._call("assess_session", scores=scores)

    async def evaluate_submission(
        self, question: str, code: str, results_summary: str,
        discussion: list[str], hints_used: int, runs: int,
    ) -> SubmissionScore:
        return await self._call(
            "evaluate_submission",
            question=question,
            code=code,
            results_summary=results_summary,
            discussion=discussion,
            hints_used=hints_used,
            runs=runs,
        )

    async def generate_warm_up_questions(self, resume_text: str) -> WarmUp:
        return await self._call("generate_warm_up_questions", resume_text=resume_text)

    async def react_to_code(
        self, question: str, code: str, results_summary: str,
        history: list[dict[str, str]],
    ) -> str:
        return await self._call(
            "react_to_code",
            question=question,
            code=code,
            results_summary=results_summary,
            history=history,
        )

    async def watch_code(
        self, question: str, code: str, stuck: bool, seconds_elapsed: float,
        runs_summary: str,
    ) -> WatchDecision:
        return await self._call(
            "watch_code",
            question=question,
            code=code,
            stuck=stuck,
            seconds_elapsed=seconds_elapsed,
            runs_summary=runs_summary,
        )

    async def coding_chat(
        self, question: str, code: str, history: list[dict[str, str]], utterance: str
    ) -> str:
        return await self._call(
            "coding_chat",
            question=question,
            code=code,
            history=history,
            utterance=utterance,
        )


def get_provider() -> LLMProvider:
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if groq_key and gemini_key:
        return FailoverProvider(GroqProvider(groq_key), GeminiProvider(gemini_key))
    if groq_key:
        return GroqProvider(groq_key)
    if gemini_key:
        return GeminiProvider(gemini_key)
    return ScriptedProvider()
