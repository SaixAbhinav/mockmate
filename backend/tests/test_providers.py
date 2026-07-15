import json

import httpx
import pytest

from app.providers import (
    AnswerScore,
    Assessment,
    GeminiProvider,
    GroqProvider,
    Judgment,
    ProviderError,
    ProviderMalformedError,
    ProviderUnavailableError,
    ScriptedProvider,
)

pytestmark = pytest.mark.anyio


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            # Mirror real httpx: the message embeds the request URL. FakeAsyncClient.post
            # records last_request before returning this response, so it's populated by
            # the time raise_for_status() runs.
            url = FakeAsyncClient.last_request["url"] if FakeAsyncClient.last_request else "unknown"
            raise httpx.HTTPStatusError(
                f"HTTP error '{self.status_code}' for url '{url}'", request=None, response=self
            )

    def json(self):
        return self._json


class FakeAsyncClient:
    """Records the last request and returns a canned response."""

    last_request = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        FakeAsyncClient.last_request = {"url": url, **kwargs}
        return FakeAsyncClient.response


@pytest.fixture
def fake_groq_client(monkeypatch):
    monkeypatch.setattr("app.providers.httpx.AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


@pytest.fixture
def fake_gemini_client(monkeypatch):
    monkeypatch.setattr("app.providers.httpx.AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


def groq_chat_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


# --- ScriptedProvider: the test fake, always advances, never probes ---


async def test_scripted_provider_always_advances():
    provider = ScriptedProvider()
    judgment = await provider.judge_answer(
        question="Q1", follow_up_hints=["h"], history=[], answer="anything"
    )
    assert judgment.classification == "advance"
    assert judgment.answered is True
    assert judgment.reply


async def test_scripted_provider_wrap_up_returns_closing_remark():
    provider = ScriptedProvider()
    text = await provider.wrap_up(transcript=[{"role": "user", "content": "hi"}])
    assert isinstance(text, str) and text


# --- GroqProvider: structured judge+reply call ---


async def test_groq_judge_answer_parses_valid_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps({"classification": "probe", "reply": "Can you say more?", "answered": False})
        )
    )
    provider = GroqProvider(api_key="fake-key")
    judgment = await provider.judge_answer(
        question="What is overfitting?",
        follow_up_hints=["ask about validation loss"],
        history=[],
        answer="It's when a model does well on training data.",
    )
    assert judgment == Judgment(classification="probe", reply="Can you say more?", answered=False)


async def test_groq_judge_answer_raises_on_malformed_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(groq_chat_response("not valid json"))
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderError):
        await provider.judge_answer(
            question="Q", follow_up_hints=["h"], history=[], answer="a"
        )


async def test_groq_judge_answer_raises_on_missing_field(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(json.dumps({"classification": "advance"}))
    )
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderError):
        await provider.judge_answer(
            question="Q", follow_up_hints=["h"], history=[], answer="a"
        )


async def test_groq_wrap_up_returns_text(fake_groq_client):
    fake_groq_client.response = FakeResponse(groq_chat_response("Great work today!"))
    provider = GroqProvider(api_key="fake-key")
    text = await provider.wrap_up(transcript=[{"role": "user", "content": "hi"}])
    assert text == "Great work today!"


async def test_groq_http_error_raises_provider_unavailable(fake_groq_client):
    fake_groq_client.response = FakeResponse({"error": "rate limited"}, status_code=429)
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderUnavailableError):
        await provider.judge_answer(question="Q", follow_up_hints=["h"], history=[], answer="a")


async def test_groq_unexpected_response_shape_raises_provider_malformed(fake_groq_client):
    fake_groq_client.response = FakeResponse({"unexpected": "shape"})
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderMalformedError):
        await provider.judge_answer(question="Q", follow_up_hints=["h"], history=[], answer="a")


# --- GeminiProvider: the API key rides in the URL, so failures must never echo it ---


async def test_gemini_http_error_raises_provider_unavailable_without_leaking_key(
    fake_gemini_client,
):
    fake_gemini_client.response = FakeResponse({"error": "rate limited"}, status_code=429)
    provider = GeminiProvider(api_key="secret-test-key-12345")
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await provider.judge_answer(question="Q", follow_up_hints=["h"], history=[], answer="a")
    message = str(exc_info.value)
    assert "429" in message
    assert "secret-test-key-12345" not in message


def test_both_failure_types_are_provider_errors():
    # Callers that don't care which failure it was (the evaluator) catch the base.
    assert issubclass(ProviderMalformedError, ProviderError)
    assert issubclass(ProviderUnavailableError, ProviderError)


async def test_scripted_provider_returns_neutral_scores():
    provider = ScriptedProvider()
    score = await provider.evaluate_answer(
        question="Q", follow_up_hints=["h"], answers=["an answer"]
    )
    assert 1 <= score.correctness <= 5
    assert 1 <= score.depth <= 5
    assert 1 <= score.clarity <= 5
    assert score.comment


async def test_scripted_provider_returns_assessment():
    provider = ScriptedProvider()
    result = await provider.assess_session([{"question": "Q"}])
    assert result.assessment
    assert isinstance(result.strengths, list)
    assert isinstance(result.improvements, list)


async def test_groq_evaluate_answer_parses_valid_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps({"correctness": 4, "depth": 3, "clarity": 5, "comment": "Solid."})
        )
    )
    provider = GroqProvider(api_key="fake-key")
    score = await provider.evaluate_answer(
        question="What is overfitting?",
        follow_up_hints=["ask about validation loss"],
        answers=["It fits noise."],
    )
    assert score == AnswerScore(correctness=4, depth=3, clarity=5, comment="Solid.")


async def test_groq_evaluate_answer_rejects_out_of_range_score(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps({"correctness": 9, "depth": 3, "clarity": 5, "comment": "x"})
        )
    )
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderMalformedError):
        await provider.evaluate_answer(question="Q", follow_up_hints=["h"], answers=["a"])


async def test_groq_evaluate_answer_raises_on_malformed_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(groq_chat_response("not json"))
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderMalformedError):
        await provider.evaluate_answer(question="Q", follow_up_hints=["h"], answers=["a"])


async def test_groq_assess_session_parses_valid_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps(
                {
                    "assessment": "Strong overall.",
                    "strengths": ["clear"],
                    "improvements": ["go deeper"],
                }
            )
        )
    )
    provider = GroqProvider(api_key="fake-key")
    result = await provider.assess_session(
        [{"question": "Q", "correctness": 4, "depth": 3, "clarity": 5, "comment": "ok"}]
    )
    assert result == Assessment(
        assessment="Strong overall.", strengths=["clear"], improvements=["go deeper"]
    )


async def test_groq_assess_session_raises_on_missing_field(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(json.dumps({"assessment": "x"}))
    )
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderMalformedError):
        await provider.assess_session([{"question": "Q"}])


async def test_groq_assess_session_raises_on_partial_score(fake_groq_client):
    # correctness/depth/clarity present but comment missing: _assess_user_turn must
    # treat this as "could not be scored" rather than raising a raw KeyError while
    # building the prompt. The fake response below is itself malformed (mirrors
    # test_groq_assess_session_raises_on_missing_field) so the only way this test
    # can end up raising ProviderMalformedError is if control reaches the response
    # parsing at all — proving _assess_user_turn didn't blow up first.
    fake_groq_client.response = FakeResponse(
        groq_chat_response(json.dumps({"assessment": "x"}))
    )
    provider = GroqProvider(api_key="fake-key")
    with pytest.raises(ProviderMalformedError):
        await provider.assess_session(
            [{"question": "Q", "correctness": 4, "depth": 3, "clarity": 5}]
        )
