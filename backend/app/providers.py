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


class ProviderError(Exception):
    """Raised when a provider's structured response is malformed."""


@dataclass(frozen=True)
class Judgment:
    classification: str
    reply: str
    answered: bool


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
        raise ProviderError(f"malformed judge response: {content!r}") from exc


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

    async def _chat_json(
        self, messages: list[dict[str, str]], max_tokens: int, json_mode: bool = True
    ) -> str:
        payload = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()


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
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


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


def get_provider() -> LLMProvider:
    if key := os.getenv("GROQ_API_KEY"):
        return GroqProvider(key)
    if key := os.getenv("GEMINI_API_KEY"):
        return GeminiProvider(key)
    return ScriptedProvider()
