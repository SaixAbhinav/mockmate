"""LLM providers behind one interface (ADR 0002).

The rest of the app only ever calls `get_provider().chat(...)`. Which model
answers — Groq, Gemini, or the scripted fallback — is a deployment detail
decided by environment variables, never by application code.
"""

import os
from typing import Protocol

import httpx

INTERVIEWER_SYSTEM_PROMPT = (
    "You are a professional but friendly technical interviewer running a mock "
    "interview. Ask exactly one question at a time. Keep every reply under 80 "
    "words so it works as spoken audio. If the candidate just answered, react "
    "briefly (one sentence) and either probe deeper or move to the next "
    "question. Never dump lists; you are speaking, not writing."
)


class LLMProvider(Protocol):
    name: str

    async def chat(self, history: list[dict[str, str]]) -> str:
        """history is a list of {"role": "user"|"assistant", "content": str}."""
        ...


class GroqProvider:
    """Groq's OpenAI-compatible endpoint. Free tier, 70B-class models."""

    name = "groq"
    _url = "https://api.groq.com/openai/v1/chat/completions"
    _model = "llama-3.3-70b-versatile"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def chat(self, history: list[dict[str, str]]) -> str:
        messages = [{"role": "system", "content": INTERVIEWER_SYSTEM_PROMPT}, *history]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "messages": messages, "max_tokens": 300},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()


class GeminiProvider:
    """Google Gemini REST API. Free tier."""

    name = "gemini"
    _model = "gemini-2.0-flash"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def chat(self, history: list[dict[str, str]]) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"text": m["content"]}]}
            for m in history
        ]
        payload = {
            "system_instruction": {"parts": [{"text": INTERVIEWER_SYSTEM_PROMPT}]},
            "contents": contents,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


class ScriptedProvider:
    """No-key fallback so the voice loop is testable without any account.

    Walks through a fixed set of interview questions; ignores answer content.
    """

    name = "scripted"
    _questions = [
        "Let's start easy: tell me a little about yourself and what you're preparing for.",
        "Alright. Explain the difference between a process and a thread.",
        "Good. Now, what happens step by step when you type a URL into a browser and press enter?",
        "Last one for this demo: what is overfitting, and how would you detect it?",
    ]

    async def chat(self, history: list[dict[str, str]]) -> str:
        asked = sum(1 for m in history if m["role"] == "assistant")
        if asked < len(self._questions):
            prefix = "" if asked == 0 else "Thanks, noted. "
            return prefix + self._questions[asked]
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
