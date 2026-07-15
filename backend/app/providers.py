"""LLM providers behind one interface (ADR 0002, ADR 0006).

The interviewer agent only ever calls `get_provider().judge_answer(...)` and
`.wrap_up(...)`. Which model answers - Groq, Gemini, or the scripted
fallback - is a deployment detail decided by environment variables, never by
application code.
"""

import json
import os
from dataclasses import dataclass
from typing import Protocol

import httpx

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
    "grade, or critique the answers - that is a separate step. Keep it under "
    "40 words; it is spoken aloud."
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

DIMENSIONS = ("correctness", "depth", "clarity")


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
class Assessment:
    """The prose half of an Evaluation: overall read, strengths, improvements."""

    assessment: str
    strengths: list[str]
    improvements: list[str]


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


def _assess_user_turn(scores: list[dict]) -> str:
    lines = []
    for s in scores:
        if s.get("skipped"):
            lines.append(f"- {s['question']}: never answered")
        elif s.get("unscored") or not all(k in s for k in (*DIMENSIONS, "comment")):
            lines.append(f"- {s['question']}: could not be scored")
        else:
            lines.append(
                f"- {s['question']}: correctness {s['correctness']}, "
                f"depth {s['depth']}, clarity {s['clarity']} — {s['comment']}"
            )
    return "Per-question results:\n" + "\n".join(lines)


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


def get_provider() -> LLMProvider:
    if key := os.getenv("GROQ_API_KEY"):
        return GroqProvider(key)
    if key := os.getenv("GEMINI_API_KEY"):
        return GeminiProvider(key)
    return ScriptedProvider()
