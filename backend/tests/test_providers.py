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
    MAX_DOMAIN_LABEL_CHARS,
    ProviderError,
    ProviderMalformedError,
    ProviderUnavailableError,
    ScriptedProvider,
    SubmissionScore,
    WarmUp,
    WatchDecision,
    _assess_user_turn,
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

    async def generate_warm_up_questions(self, resume_text):
        return await self._respond(
            "generate_warm_up_questions",
            WarmUp(
                domain=f"{self.name} domain",
                questions=[
                    {
                        "topic": "t",
                        "difficulty": "easy",
                        "question": f"{self.name} Q",
                        "follow_up_hints": ["h"],
                    }
                ],
            ),
        )

    async def react_to_code(self, question, code, results_summary, history):
        return await self._respond("react_to_code", f"{self.name} reaction")

    async def watch_code(self, question, code, stuck, seconds_elapsed, runs_summary):
        return await self._respond(
            "watch_code", WatchDecision(action="ask", remark=f"{self.name} watch")
        )

    async def coding_chat(self, question, code, history, utterance):
        return await self._respond("coding_chat", f"{self.name} chat")

    async def evaluate_submission(
        self, question, code, results_summary, discussion, hints_used, runs
    ):
        return await self._respond(
            "evaluate_submission", SubmissionScore(3, 3, f"{self.name} submission")
        )


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
    # Empty questions = "I can't do this" — the endpoint falls back to the bank.
    provider = ScriptedProvider()
    result = await provider.generate_warm_up_questions("resume text")
    assert result.questions == []


async def test_groq_generate_warm_up_questions_parses_valid_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps(
                {
                    "domain": "web development",
                    "questions": [
                        warm_up_entry("Q1", "easy"),
                        warm_up_entry("Q2", "medium"),
                        warm_up_entry("Q3", "medium"),
                    ],
                }
            )
        )
    )
    provider = GroqProvider(api_key="fake-key")

    result = await provider.generate_warm_up_questions("I built things.")

    assert result.domain == "web development"
    assert [q["question"] for q in result.questions] == ["Q1", "Q2", "Q3"]
    assert result.questions[0]["follow_up_hints"] == ["Ask about X"]


async def test_groq_generate_warm_up_rejects_missing_domain(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps({"questions": [warm_up_entry("Q1", "easy"),
                                      warm_up_entry("Q2", "easy")]})
        )
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume")


async def test_groq_generate_warm_up_rejects_blank_domain(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps({"domain": "   ",
                        "questions": [warm_up_entry("Q1", "easy"),
                                      warm_up_entry("Q2", "easy")]})
        )
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume")


async def test_groq_generate_warm_up_truncates_a_rambling_domain(fake_groq_client):
    # The label is displayed; a model that writes a paragraph must not break the UI.
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps({"domain": "x" * 200,
                        "questions": [warm_up_entry("Q1", "easy"),
                                      warm_up_entry("Q2", "easy")]})
        )
    )
    provider = GroqProvider(api_key="fake-key")

    result = await provider.generate_warm_up_questions("resume")

    assert len(result.domain) == MAX_DOMAIN_LABEL_CHARS


async def test_groq_generate_warm_up_rejects_wrong_count(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps({"domain": "ml", "questions": [warm_up_entry("Q1", "easy")]})
        )
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume")


async def test_groq_generate_warm_up_rejects_bad_difficulty(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            json.dumps(
                {
                    "domain": "ml",
                    "questions": [warm_up_entry("Q1", "trivial"),
                                  warm_up_entry("Q2", "easy")],
                }
            )
        )
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume")


async def test_groq_generate_warm_up_raises_on_malformed_json(fake_groq_client):
    fake_groq_client.response = FakeResponse(groq_chat_response("not json"))
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.generate_warm_up_questions("resume")


async def test_failover_delegates_generate_warm_up_questions():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    result = await provider.generate_warm_up_questions(resume_text="r")

    assert result.questions[0]["question"] == "secondary Q"
    assert result.domain == "secondary domain"


# --- DSA code reaction (ADR 0017) ---


async def test_scripted_provider_reaction_asks_about_the_approach():
    provider = ScriptedProvider()

    reaction = await provider.react_to_code(
        "Q", "def f(): pass", "0 of 2 test cases passed.", history=[]
    )

    assert "approach" in reaction.lower()


async def test_groq_react_to_code_returns_plain_text(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response("Nice - all tests pass. Why a set here?")
    )
    provider = GroqProvider(api_key="fake-key")

    reaction = await provider.react_to_code(
        "Q", "def f(): pass", "2 of 2 test cases passed.", history=[]
    )

    assert reaction == "Nice - all tests pass. Why a set here?"


async def test_failover_delegates_react_to_code():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    reaction = await provider.react_to_code(
        question="Q", code="def f(): pass", results_summary="summary", history=[]
    )

    assert reaction == "secondary reaction"


# --- The watching interviewer (ADR 0018/0019) ---

NO_RUNS = "The candidate has not run the tests yet."


async def test_scripted_watcher_stays_silent():
    provider = ScriptedProvider()

    decision = await provider.watch_code(
        "Q", "def f(): pass", stuck=True, seconds_elapsed=120.0, runs_summary=NO_RUNS
    )

    assert decision == WatchDecision(action="silent", remark="")


async def test_groq_watch_code_parses_a_decision(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response('{"action": "hint", "remark": "Try a running total."}')
    )
    provider = GroqProvider(api_key="fake-key")

    decision = await provider.watch_code(
        "Q", "def f(): pass", stuck=True, seconds_elapsed=90.0, runs_summary=NO_RUNS
    )

    assert decision == WatchDecision(action="hint", remark="Try a running total.")


async def test_groq_watch_code_rejects_unknown_action(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response('{"action": "shout", "remark": "hey"}')
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.watch_code(
            "Q", "code", stuck=False, seconds_elapsed=90.0, runs_summary=NO_RUNS
        )


async def test_groq_watch_code_rejects_speaking_without_a_remark(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response('{"action": "ask", "remark": "   "}')
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.watch_code(
            "Q", "code", stuck=False, seconds_elapsed=90.0, runs_summary=NO_RUNS
        )


async def test_failover_delegates_watch_code():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    decision = await provider.watch_code(
        question="Q", code="c", stuck=False, seconds_elapsed=80.0, runs_summary=NO_RUNS
    )

    assert decision.remark == "secondary watch"


async def test_scripted_coding_chat_returns_a_spoken_line():
    provider = ScriptedProvider()

    reply = await provider.coding_chat("Q", "def f(): pass", history=[], utterance="hm")

    assert "listening" in reply.lower()


async def test_groq_coding_chat_returns_plain_text(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response("Good question - yes, the list can be empty.")
    )
    provider = GroqProvider(api_key="fake-key")

    reply = await provider.coding_chat(
        "Q", "def f(): pass", history=[], utterance="Can the list be empty?"
    )

    assert reply == "Good question - yes, the list can be empty."


async def test_failover_delegates_coding_chat():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    reply = await provider.coding_chat(
        question="Q", code="c", history=[], utterance="hm"
    )

    assert reply == "secondary chat"


# --- Scoring the coding round (ADR 0020) ---


async def test_scripted_provider_scores_a_submission():
    provider = ScriptedProvider()

    score = await provider.evaluate_submission(
        question="Q",
        code="def f(nums):\n    return sum(nums)\n",
        results_summary="status ok, passed 2 of 4",
        discussion=["I summed the list."],
        hints_used=1,
        runs=3,
    )

    assert (score.code_quality, score.approach) == (3, 3)
    assert score.comment


async def test_groq_evaluate_submission_parses_a_score(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response(
            '{"code_quality": 4, "approach": 3, "comment": "Clean loop; missed the empty case."}'
        )
    )
    provider = GroqProvider(api_key="fake-key")

    score = await provider.evaluate_submission(
        question="Q",
        code="def f(): pass",
        results_summary="status ok, passed 2 of 4",
        discussion=[],
        hints_used=0,
        runs=1,
    )

    assert score == SubmissionScore(
        code_quality=4, approach=3, comment="Clean loop; missed the empty case."
    )


async def test_groq_evaluate_submission_rejects_out_of_range_scores(fake_groq_client):
    fake_groq_client.response = FakeResponse(
        groq_chat_response('{"code_quality": 9, "approach": 3, "comment": "x"}')
    )
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.evaluate_submission(
            question="Q", code="c", results_summary="s", discussion=[], hints_used=0, runs=0
        )


async def test_groq_evaluate_submission_rejects_missing_fields(fake_groq_client):
    fake_groq_client.response = FakeResponse(groq_chat_response('{"code_quality": 4}'))
    provider = GroqProvider(api_key="fake-key")

    with pytest.raises(ProviderMalformedError):
        await provider.evaluate_submission(
            question="Q", code="c", results_summary="s", discussion=[], hints_used=0, runs=0
        )


async def test_failover_delegates_evaluate_submission():
    primary = OneSidedProvider("primary", error=ProviderUnavailableError("429"))
    secondary = OneSidedProvider("secondary")
    provider = FailoverProvider(primary, secondary)

    score = await provider.evaluate_submission(
        question="Q", code="c", results_summary="s", discussion=[], hints_used=0, runs=0
    )

    assert score.comment == "secondary submission"


async def test_assess_user_turn_formats_a_coding_line():
    text = _assess_user_turn(
        [
            {"question": "Q1", "correctness": 4, "depth": 3, "clarity": 4, "comment": "ok"},
            {
                "question": "Implement running_sum",
                "kind": "dsa",
                "tests": {"status": "ok", "passed": 3, "total": 4},
                "code_quality": 4,
                "approach": 3,
                "comment": "solid",
                "hints": 1,
                "runs": 2,
            },
        ]
    )

    assert "passed 3 of 4" in text
    assert "code quality 4" in text
    assert "1 hint(s)" in text
