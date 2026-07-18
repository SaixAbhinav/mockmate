import json

import httpx
import pytest

from app.providers import (
    AnswerScore,
    Assessment,
    FailoverProvider,
    GeminiProvider,
    GroqProvider,
    Judgment,
    ProviderError,
    ProviderMalformedError,
    ProviderUnavailableError,
    ScriptedProvider,
    get_provider,
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


# --- FailoverProvider: Groq primary, Gemini secondary (ADR 0014) ---


class OneSidedProvider:
    """Test double for failover: every method returns a canned value or raises."""

    def __init__(self, name, error=None):
        self.name = name
        self.error = error
        self.calls = []

    async def _respond(self, method, value):
        self.calls.append(method)
        if self.error:
            raise self.error
        return value

    async def judge_answer(self, question, follow_up_hints, history, answer):
        return await self._respond("judge_answer", Judgment("advance", f"{self.name} reply", True))

    async def wrap_up(self, transcript):
        return await self._respond("wrap_up", f"{self.name} closing")

    async def evaluate_answer(self, question, follow_up_hints, answers):
        return await self._respond("evaluate_answer", AnswerScore(3, 3, 3, self.name))

    async def assess_session(self, scores):
        return await self._respond("assess_session", Assessment(self.name, [], []))

    async def generate_warm_up_questions(self, resume_text, domain):
        return await self._respond(
            "generate_warm_up_questions",
            [
                {
                    "topic": "t",
                    "difficulty": "easy",
                    "question": f"{self.name} Q",
                    "follow_up_hints": ["h"],
                }
            ],
        )

    async def react_to_code(self, question, code, results_summary):
        return await self._respond("react_to_code", f"{self.name} reaction")


async def test_failover_returns_primary_result_without_touching_secondary():
    primary, secondary = OneSidedProvider("primary"), OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    judgment = await provider.judge_answer(
        question="Q", follow_up_hints=["h"], history=[], answer="a"
    )

    assert judgment.reply == "primary reply"
    assert secondary.calls == []


async def test_failover_uses_secondary_when_primary_unavailable():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    judgment = await provider.judge_answer(
        question="Q", follow_up_hints=["h"], history=[], answer="a"
    )

    assert judgment.reply == "secondary reply"
    assert primary.calls == ["judge_answer"] and secondary.calls == ["judge_answer"]


async def test_failover_covers_every_provider_method():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("down"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    assert (await provider.wrap_up([])) == "secondary closing"
    score = await provider.evaluate_answer(question="Q", follow_up_hints=["h"], answers=["a"])
    assert score.comment == "secondary"
    assert (await provider.assess_session([])).assessment == "secondary"


async def test_failover_does_not_retry_malformed_replies():
    # Malformed is deterministic, not an outage; each caller already has its own
    # malformed-recovery (ADR 0013). Retrying elsewhere would mask real bugs.
    primary = OneSidedProvider("primary", error=ProviderMalformedError("bad json"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    with pytest.raises(ProviderMalformedError):
        await provider.judge_answer(question="Q", follow_up_hints=["h"], history=[], answer="a")

    assert secondary.calls == []


async def test_failover_raises_when_both_sides_unavailable():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary", error=ProviderUnavailableError("quota"))
    provider = FailoverProvider(primary, secondary)

    with pytest.raises(ProviderUnavailableError):
        await provider.judge_answer(question="Q", follow_up_hints=["h"], history=[], answer="a")


def test_get_provider_returns_failover_when_both_keys_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g1")
    monkeypatch.setenv("GEMINI_API_KEY", "g2")

    assert get_provider().name == "groq+gemini"


# --- Warm-up question generation (ADR 0015) ---


def warm_up_entry(question="Q", difficulty="easy"):
    return {
        "topic": "projects",
        "difficulty": difficulty,
        "question": question,
        "follow_up_hints": ["Ask about X"],
    }


async def test_scripted_provider_generates_no_warm_up_questions():
    # Empty list = "I can't do this" — the endpoint falls back to the curated bank.
    provider = ScriptedProvider()
    assert await provider.generate_warm_up_questions("resume text", "ml_genai") == []


async def test_groq_generate_warm_up_questions_parses_valid_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps(
                {
                    "questions": [
                        warm_up_entry("Q1", "easy"),
                        warm_up_entry("Q2", "medium"),
                        warm_up_entry("Q3", "medium"),
                    ]
                }
            )
        )
    )
    provider = GroqProvider(api_key="fake-key")

    questions = await provider.generate_warm_up_questions("I built things.", "ml_genai")

    assert [q["question"] for q in questions] == ["Q1", "Q2", "Q3"]
    assert questions[0]["follow_up_hints"] == ["Ask about X"]


async def test_groq_generate_warm_up_rejects_wrong_count(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(json.dumps({"questions": [warm_up_entry("only one")]}))
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume", "ml_genai")


async def test_groq_generate_warm_up_rejects_bad_difficulty(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps(
                {"questions": [warm_up_entry("Q1"), warm_up_entry("Q2", "impossible")]}
            )
        )
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume", "ml_genai")


async def test_groq_generate_warm_up_raises_on_malformed_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(groq_chat_response("not json"))
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume", "ml_genai")


async def test_failover_delegates_generate_warm_up_questions():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    questions = await provider.generate_warm_up_questions(resume_text="r", domain="ml_genai")

    assert questions[0]["question"] == "secondary Q"


# --- DSA code reaction (ADR 0017) ---


async def test_scripted_provider_reaction_asks_about_the_approach():
    provider = ScriptedProvider()

    reaction = await provider.react_to_code("Q", "def f(): pass", "0 of 2 test cases passed.")

    assert "approach" in reaction.lower()


async def test_groq_react_to_code_returns_plain_text(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response("Nice - all tests pass. Why a set here?")
    )
    provider = GroqProvider(api_key="fake-key")

    reaction = await provider.react_to_code("Q", "def f(): pass", "2 of 2 test cases passed.")

    assert reaction == "Nice - all tests pass. Why a set here?"


async def test_failover_delegates_react_to_code():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    reaction = await provider.react_to_code(
        question="Q", code="def f(): pass", results_summary="summary"
    )

    assert reaction == "secondary reaction"
