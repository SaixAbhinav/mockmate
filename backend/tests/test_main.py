import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers import ProviderUnavailableError, Judgment


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def fake_synthesize(text, voice=None):
        return b"fake-audio-bytes"

    monkeypatch.setattr("app.main.synthesize", fake_synthesize)
    return TestClient(app)


def test_create_session_returns_first_question(client):
    resp = client.post("/api/session", json={"domain": "ml_genai"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["first_question"]
    assert data["audio_b64"]
    assert data["question_number"] == 1
    assert data["total_questions"] == 6  # intro + 3 warm-up + 2 DSA (ADR 0012)


def test_create_session_rejects_unknown_domain(client):
    resp = client.post("/api/session", json={"domain": "nope"})
    assert resp.status_code == 400


def test_answer_advances_with_scripted_provider(client):
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]

    resp = client.post(f"/api/session/{session_id}/answer", json={"transcript": "my answer"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"]
    assert data["audio_b64"]
    assert data["phase"] in ("advancing", "done")
    assert data["question_number"] >= 1


def test_answer_unknown_session_returns_404(client):
    resp = client.post("/api/session/does-not-exist/answer", json={"transcript": "x"})
    assert resp.status_code == 404


DSA_STUB_CODE = "x = 1"  # defines nothing; the run errors, but a Submission is a Submission


def _drive_to_done(client, session_id):
    for _ in range(30):
        resp = client.post(f"/api/session/{session_id}/answer", json={"transcript": "answer"})
        data = resp.json()
        if data.get("dsa"):  # a coding question awaits a Submission (ADR 0019: answering just chats)
            client.post(f"/api/session/{session_id}/dsa/submit", json={"code": DSA_STUB_CODE})
            continue
        if data["phase"] == "done":
            return
    raise AssertionError("session never reached done")


def test_full_session_reaches_done(client):
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]
    _drive_to_done(client, session_id)


def test_turn_endpoint_removed(client):
    resp = client.post("/api/turn", json={"history": []})
    assert resp.status_code == 404


def test_answer_returns_503_when_provider_unavailable(client, monkeypatch):
    from app import main as main_module

    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]

    async def unavailable(*args, **kwargs):
        raise ProviderUnavailableError("rate limited")

    monkeypatch.setattr(main_module, "submit_answer", unavailable)

    resp = client.post(f"/api/session/{session_id}/answer", json={"transcript": "a"})

    assert resp.status_code == 503


def _finish_session(client) -> str:
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]
    _drive_to_done(client, session_id)
    return session_id


def test_evaluation_unknown_session_returns_404(client):
    resp = client.get("/api/session/does-not-exist/evaluation")
    assert resp.status_code == 404


def test_evaluation_before_interview_finished_returns_409(client):
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]
    resp = client.get(f"/api/session/{session_id}/evaluation")
    assert resp.status_code == 409


def test_evaluation_returns_scores_for_finished_session(client):
    session_id = _finish_session(client)

    resp = client.get(f"/api/session/{session_id}/evaluation")

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["domain"] == "ml_genai"
    assert data["assessment"]
    assert set(data["averages"]) == {"correctness", "depth", "clarity"}
    assert data["coverage"]["total"] == len(data["questions"])
    assert len(data["questions"]) == 3  # 3 warm-ups; the intro is excluded (ADR 0015)
    first = data["questions"][0]
    assert first["question"]
    assert 1 <= first["correctness"] <= 5


def test_evaluation_includes_the_coding_round(client):
    session_id = _finish_session(client)

    data = client.get(f"/api/session/{session_id}/evaluation").json()

    dsa = data["dsa"]
    assert len(dsa["questions"]) == 2  # one easier + one harder (ADR 0016)
    entry = dsa["questions"][0]
    # DSA_STUB_CODE ("x = 1") never defines the function: the Runner reports
    # status "error" with zero cases - real facts, even in the keyless demo.
    assert entry["tests"] == {"status": "error", "passed": 0, "total": 0}
    assert entry["code_quality"] == 3  # the scripted provider's canned judgment
    assert set(dsa["averages"]) == {"code_quality", "approach"}
    assert dsa["hints_used"] == 0


def test_evaluation_is_cached_per_session(client, monkeypatch):
    from app import main as main_module

    session_id = _finish_session(client)
    calls = []
    original = main_module.evaluate_session

    async def counting(*args, **kwargs):
        calls.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(main_module, "evaluate_session", counting)

    first = client.get(f"/api/session/{session_id}/evaluation").json()
    second = client.get(f"/api/session/{session_id}/evaluation").json()

    assert first == second
    assert len(calls) == 1  # second request served from cache


@pytest.mark.anyio
async def test_concurrent_evaluation_requests_score_only_once(monkeypatch, anyio_backend):
    # <StrictMode> double-invokes effects, so two concurrent GETs are guaranteed
    # in dev. Without the lock both miss the cache and the Session is scored twice.
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from app import main as main_module

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def fake_synthesize(text, voice=None):
        return b"fake-audio-bytes"

    monkeypatch.setattr(main_module, "synthesize", fake_synthesize)

    calls = []
    original = main_module.evaluate_session

    async def counting(*args, **kwargs):
        calls.append(1)
        await asyncio.sleep(0.05)  # widen the race window
        return await original(*args, **kwargs)

    monkeypatch.setattr(main_module, "evaluate_session", counting)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        sid = (await ac.post("/api/session", json={"domain": "ml_genai"})).json()["session_id"]
        for _ in range(30):
            resp = await ac.post(f"/api/session/{sid}/answer", json={"transcript": "a"})
            data = resp.json()
            if data.get("dsa"):
                await ac.post(f"/api/session/{sid}/dsa/submit", json={"code": "x = 1"})
                continue
            if data["phase"] == "done":
                break

        first, second = await asyncio.gather(
            ac.get(f"/api/session/{sid}/evaluation"),
            ac.get(f"/api/session/{sid}/evaluation"),
        )

    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()
    assert len(calls) == 1


def test_evaluation_with_retryable_failure_is_not_cached(client, monkeypatch):
    from app import main as main_module

    session_id = _finish_session(client)
    calls = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        return {
            "session_id": session_id,
            "domain": "ml_genai",
            "averages": {"correctness": None, "depth": None, "clarity": None},
            "coverage": {"answered": 0, "total": 0},
            "assessment": "Could not generate an overall assessment for this interview.",
            "strengths": [],
            "improvements": [],
            "questions": [],
            "dsa": {
                "averages": {"code_quality": None, "approach": None},
                "hints_used": 0,
                "questions": [],
            },
            "retryable_failure": True,
        }

    monkeypatch.setattr(main_module, "evaluate_session", flaky)

    first = client.get(f"/api/session/{session_id}/evaluation")
    second = client.get(f"/api/session/{session_id}/evaluation")

    assert first.status_code == 200
    assert "retryable_failure" not in first.json()
    assert second.status_code == 200
    assert len(calls) == 2  # not cached — evaluate_session ran on both requests


# Comfortably over the 200-char floor; contains "LangGraph" for the grounding assert.
SAMPLE_RESUME = (
    b"I built MockMate, a voice-based mock interviewer, using LangGraph "
    b"agents, FastAPI, and React, with a fully tested backend. " * 3
)


def _upload_resume(client, text=SAMPLE_RESUME):
    return client.post(
        "/api/resume", files={"file": ("resume.txt", text, "text/plain")}
    )


def test_upload_txt_resume_returns_id(client):
    resp = _upload_resume(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"]
    assert data["characters"] == len(SAMPLE_RESUME.decode().strip())


def test_upload_unreadable_resume_returns_400(client):
    resp = client.post(
        "/api/resume", files={"file": ("resume.pdf", b"not a pdf", "application/pdf")}
    )
    assert resp.status_code == 400


def test_create_session_with_unknown_resume_returns_404(client):
    resp = client.post("/api/session", json={"domain": "ml_genai", "resume_id": "nope"})
    assert resp.status_code == 404


def test_first_question_is_the_intro(client):
    data = client.post("/api/session", json={"domain": "ml_genai"}).json()

    assert data["stage"] == "intro"
    assert data["question_number"] == 1
    assert "tell me about yourself" in data["first_question"].lower()


def test_session_with_resume_uses_generated_warm_up(client, monkeypatch):
    from app import main as main_module

    class GeneratingProvider:
        name = "fake"

        async def generate_warm_up_questions(self, resume_text, domain):
            assert "LangGraph" in resume_text  # the stored text reaches the provider
            return [
                {"topic": "projects", "difficulty": "easy",
                 "question": "Tell me about MockMate.", "follow_up_hints": ["Ask about the evaluator"]},
                {"topic": "skills", "difficulty": "medium",
                 "question": "How did you test the agent?", "follow_up_hints": ["Ask about fakes"]},
            ]

    monkeypatch.setattr(main_module, "get_provider", lambda: GeneratingProvider())
    resume_id = _upload_resume(client).json()["resume_id"]

    data = client.post(
        "/api/session", json={"domain": "ml_genai", "resume_id": resume_id}
    ).json()

    assert data["total_questions"] == 5  # intro + 2 generated + 2 DSA
    assert data["warm_up_source"] == "resume"


def test_session_falls_back_to_bank_when_generation_fails(client, monkeypatch):
    from app import main as main_module

    class FailingProvider:
        name = "fake"

        async def generate_warm_up_questions(self, resume_text, domain):
            raise ProviderUnavailableError("429")

    monkeypatch.setattr(main_module, "get_provider", lambda: FailingProvider())
    resume_id = _upload_resume(client).json()["resume_id"]

    resp = client.post("/api/session", json={"domain": "ml_genai", "resume_id": resume_id})

    assert resp.status_code == 200  # a failed generation never blocks a Session
    data = resp.json()
    assert data["total_questions"] == 6  # intro + 3 curated + 2 DSA
    assert data["warm_up_source"] == "bank"  # degradation is labeled, never silent


# --- The DSA round's endpoints (ADR 0017) ---

from app.questions import DsaQuestion

ECHO_DSA_QUESTION = DsaQuestion(
    domain="dsa",
    topic="warmup",
    difficulty="easy",
    question="Implement echo: return the argument unchanged.",
    follow_up_hints=["Ask about the identity function"],
    function_name="echo",
    signature="def echo(x):",
    starter_code="def echo(x):\n    pass\n",
    test_cases=[{"args": [1], "expected": 1}, {"args": ["a"], "expected": "a"}],
)

ECHO_SOLUTION = "def echo(x):\n    return x\n"


def _reach_dsa(client, monkeypatch):
    """Start a Session whose single DSA question is the fixed echo question,
    then answer through intro + warm-up until it is current."""
    monkeypatch.setattr("app.agent.plan_dsa", lambda **kwargs: [ECHO_DSA_QUESTION])
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]
    for _ in range(4):  # intro + 3 curated warm-ups, scripted provider advances each
        data = client.post(
            f"/api/session/{session_id}/answer", json={"transcript": "answer"}
        ).json()
    assert data["stage"] == "dsa"
    assert data["dsa"]["function_name"] == "echo"
    assert data["dsa"]["starter_code"]
    return session_id


def test_run_executes_code_against_the_test_cases(client, monkeypatch):
    session_id = _reach_dsa(client, monkeypatch)

    resp = client.post(f"/api/session/{session_id}/dsa/run", json={"code": ECHO_SOLUTION})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert (data["passed"], data["total"]) == (2, 2)
    assert data["results"][0]["passed"] is True


def test_run_outside_the_dsa_stage_returns_409(client):
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]

    resp = client.post(f"/api/session/{session_id}/dsa/run", json={"code": "x = 1"})

    assert resp.status_code == 409


def test_answer_during_coding_chats_without_advancing(client, monkeypatch):
    """ADR 0019 behavior change: what was a 409 (ADR 0017) is now a side
    conversation - voice is live while coding, but nothing advances and the
    Submission is still the only way past the question."""
    session_id = _reach_dsa(client, monkeypatch)

    resp = client.post(
        f"/api/session/{session_id}/answer", json={"transcript": "Can the input be empty?"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"]  # the scripted chat line
    assert data["dsa"]["function_name"] == "echo"  # still on the coding question
    assert data["question_number"] == 5  # intro + 3 warm-ups done, DSA current - unmoved

    # The Submission is still the only way forward:
    submit = client.post(f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION})
    assert submit.status_code == 200
    assert submit.json()["phase"] == "probing"


def test_submit_returns_reaction_and_opens_the_discussion(client, monkeypatch):
    session_id = _reach_dsa(client, monkeypatch)

    resp = client.post(f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION})

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"]
    assert data["audio_b64"]
    assert data["phase"] == "probing"
    assert data["stage"] == "dsa"
    assert data["run"]["passed"] == 2

    # The spoken discussion now flows through the normal answer endpoint …
    followed = client.post(f"/api/session/{session_id}/answer", json={"transcript": "I returned x."})
    assert followed.status_code == 200
    assert followed.json()["phase"] == "done"  # only 1 DSA question in this fixture


def test_second_submit_for_the_same_question_returns_409(client, monkeypatch):
    session_id = _reach_dsa(client, monkeypatch)
    client.post(f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION})

    resp = client.post(f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION})

    assert resp.status_code == 409


def test_failed_reaction_leaves_the_session_untouched(client, monkeypatch):
    """The ordering guarantee at the heart of ADR 0017: run, then react, then
    mutate. A provider failure between run and react must leave the Session
    exactly as it was — no Submission recorded, so a retry with a working
    provider succeeds as if the failed attempt never happened."""
    from app import main as main_module
    from app.providers import ProviderUnavailableError

    session_id = _reach_dsa(client, monkeypatch)
    real_get_provider = main_module.get_provider

    class FailingReactionProvider:
        name = "fake"

        async def react_to_code(self, question, code, results_summary, history):
            raise ProviderUnavailableError("rate limited")

    monkeypatch.setattr(main_module, "get_provider", lambda: FailingReactionProvider())

    failed = client.post(f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION})
    assert failed.status_code == 503

    # No Submission was attached: if the failed attempt had recorded one, this
    # retry would 409 as a second submit. It succeeds - the failure cost nothing.
    monkeypatch.setattr(main_module, "get_provider", real_get_provider)
    retried = client.post(f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION})
    assert retried.status_code == 200
    assert retried.json()["run"]["passed"] == 2


def test_dsa_payload_hidden_after_submission_with_probe_response(client, monkeypatch):
    """After submitting DSA code, if the post-submit discussion receives a 'probe'
    classification (not 'advance'), the editor must remain closed (dsa: null).

    The bug: _dsa_payload only checked stage != "dsa", not whether a submission
    existed. During probing/clarifying after submit, stage stayed "dsa" and the
    payload would reappear, reopening the editor mid-discussion.
    """
    from app import main as main_module

    session_id = _reach_dsa(client, monkeypatch)

    # Submit code successfully
    submit_resp = client.post(
        f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION}
    )
    assert submit_resp.status_code == 200
    assert submit_resp.json()["phase"] == "probing"

    # Now provide a judge that classifies the next response as "probe" (not "advance")
    # This keeps phase as "probing" and stage as "dsa", with submission persisting
    class ProbeProvider:
        name = "fake"

        async def judge_answer(
            self, question: str, follow_up_hints: list[str], history: list, answer: str
        ) -> Judgment:
            return Judgment(
                classification="probe",
                reply="Can you tell me more about that?",
                answered=True,
            )

    monkeypatch.setattr(main_module, "get_provider", lambda: ProbeProvider())

    # Call /answer during the probing phase
    answer_resp = client.post(
        f"/api/session/{session_id}/answer", json={"transcript": "I returned x."}
    )

    assert answer_resp.status_code == 200
    data = answer_resp.json()
    # The bug would have dsa != None here; the fix should return dsa: null
    assert data["dsa"] is None, (
        "After submitting DSA code, the editor should close even during "
        "post-submit probe/clarify discussion"
    )


# --- The watching interviewer (ADR 0018/0019) ---

from app.providers import ScriptedProvider, WatchDecision
from app.watcher import (
    CHAT_CAP_REMARK,
    CHECK_IN_INTERVAL_SECONDS,
    INTERJECTION_COOLDOWN_SECONDS,
    MAX_CHATS_PER_QUESTION,
    OFFER_AFTER_SECONDS,
    OFFER_REMARK,
)

EDITED_CODE = "def echo(x):\n    return x"


class _Clock:
    """Monkeypatch target for app.main._now: tests move time, never sleep."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class HintingWatcher(ScriptedProvider):
    """Scripted provider that always wants to speak on a Check-in."""

    def __init__(self):
        self.watch_calls = 0
        self.last_stuck = None
        self.last_runs_summary = None

    async def watch_code(self, question, code, stuck, seconds_elapsed, runs_summary):
        self.watch_calls += 1
        self.last_stuck = stuck
        self.last_runs_summary = runs_summary
        return WatchDecision(action="hint", remark="Try a running total.")


def _watching_session(client, monkeypatch):
    """A Session on the echo DSA question, with a controlled clock and a
    watcher that speaks whenever the policy lets it."""
    session_id = _reach_dsa(client, monkeypatch)
    clock = _Clock()
    monkeypatch.setattr("app.main._now", clock)
    watcher = HintingWatcher()
    monkeypatch.setattr("app.main.get_provider", lambda: watcher)
    return session_id, clock, watcher


def _snapshot(client, session_id, code):
    return client.post(f"/api/session/{session_id}/dsa/snapshot", json={"code": code})


def _check_in(client, session_id):
    return client.post(f"/api/session/{session_id}/dsa/check-in", json={})


def test_snapshot_is_accepted_on_a_coding_question(client, monkeypatch):
    session_id = _reach_dsa(client, monkeypatch)

    resp = _snapshot(client, session_id, EDITED_CODE)

    assert resp.status_code == 200
    assert resp.json() == {"received": True}


def test_snapshot_outside_the_dsa_stage_returns_409(client):
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]

    resp = _snapshot(client, session_id, "x = 1")

    assert resp.status_code == 409


def test_snapshot_after_submission_returns_409(client, monkeypatch):
    session_id = _reach_dsa(client, monkeypatch)
    client.post(f"/api/session/{session_id}/dsa/submit", json={"code": ECHO_SOLUTION})

    resp = _snapshot(client, session_id, "late")

    assert resp.status_code == 409


def test_check_in_is_silent_before_typing_plus_the_interval(client, monkeypatch):
    session_id, clock, watcher = _watching_session(client, monkeypatch)
    _snapshot(client, session_id, EDITED_CODE)  # typing starts
    clock.advance(CHECK_IN_INTERVAL_SECONDS - 1)

    resp = _check_in(client, session_id)

    assert resp.status_code == 200
    assert resp.json()["action"] == "silent"
    assert watcher.watch_calls == 0  # the gate never woke the LLM


def test_check_in_speaks_after_typing_plus_the_interval(client, monkeypatch):
    from app.main import _sessions

    session_id, clock, watcher = _watching_session(client, monkeypatch)
    _snapshot(client, session_id, EDITED_CODE)
    clock.advance(CHECK_IN_INTERVAL_SECONDS)

    resp = _check_in(client, session_id)

    data = resp.json()
    assert data["action"] == "hint"
    assert data["remark"] == "Try a running total."
    assert data["audio_b64"]
    assert watcher.watch_calls == 1
    assert watcher.last_stuck is False  # they edited since the starter
    assert _sessions[session_id]["transcript"][-1] == {
        "role": "assistant",
        "content": "Try a running total.",
    }


def test_first_look_on_unchanged_code_reports_stuck(client, monkeypatch):
    session_id, clock, watcher = _watching_session(client, monkeypatch)
    _snapshot(client, session_id, ECHO_DSA_QUESTION.starter_code + "\n")  # whitespace only
    clock.advance(CHECK_IN_INTERVAL_SECONDS)

    _check_in(client, session_id)

    assert watcher.last_stuck is True


def test_two_minutes_of_silence_earns_the_offer(client, monkeypatch):
    from app.main import _sessions

    session_id, clock, watcher = _watching_session(client, monkeypatch)
    _check_in(client, session_id)  # arms the watch at t0
    clock.advance(OFFER_AFTER_SECONDS)

    resp = _check_in(client, session_id)

    data = resp.json()
    assert data["action"] == "offer"
    assert data["remark"] == OFFER_REMARK
    assert data["audio_b64"]
    assert watcher.watch_calls == 0  # deterministic - no LLM involved
    assert _sessions[session_id]["transcript"][-1] == {
        "role": "assistant",
        "content": OFFER_REMARK,
    }


def test_after_the_offer_the_llm_takes_over(client, monkeypatch):
    session_id, clock, watcher = _watching_session(client, monkeypatch)
    _check_in(client, session_id)  # arms the watch
    clock.advance(OFFER_AFTER_SECONDS)
    _check_in(client, session_id)  # the Offer
    clock.advance(INTERJECTION_COOLDOWN_SECONDS)

    resp = _check_in(client, session_id)

    assert resp.json()["action"] == "hint"
    assert watcher.watch_calls == 1
    assert watcher.last_stuck is True  # still nothing typed - now honestly stuck


def test_check_in_holds_the_cooldown_after_speaking(client, monkeypatch):
    session_id, clock, watcher = _watching_session(client, monkeypatch)
    _snapshot(client, session_id, EDITED_CODE)
    clock.advance(CHECK_IN_INTERVAL_SECONDS)
    _check_in(client, session_id)  # speaks (hint)
    clock.advance(CHECK_IN_INTERVAL_SECONDS)  # past the interval, inside the 90 s cooldown

    resp = _check_in(client, session_id)

    assert resp.json()["action"] == "silent"
    assert watcher.watch_calls == 1


def test_run_results_reach_the_watcher(client, monkeypatch):
    session_id, clock, watcher = _watching_session(client, monkeypatch)
    _snapshot(client, session_id, ECHO_SOLUTION)
    client.post(f"/api/session/{session_id}/dsa/run", json={"code": ECHO_SOLUTION})
    clock.advance(CHECK_IN_INTERVAL_SECONDS)

    _check_in(client, session_id)

    assert "1" in watcher.last_runs_summary
    assert "2 of 2" in watcher.last_runs_summary


def test_check_in_failure_stays_silent(client, monkeypatch):
    class FailingWatcher(ScriptedProvider):
        async def watch_code(self, question, code, stuck, seconds_elapsed, runs_summary):
            raise ProviderUnavailableError("rate limited")

    session_id = _reach_dsa(client, monkeypatch)
    clock = _Clock()
    monkeypatch.setattr("app.main._now", clock)
    monkeypatch.setattr("app.main.get_provider", lambda: FailingWatcher())
    _snapshot(client, session_id, EDITED_CODE)
    clock.advance(CHECK_IN_INTERVAL_SECONDS)

    resp = _check_in(client, session_id)

    assert resp.status_code == 200  # a poll never surfaces a provider error
    assert resp.json()["action"] == "silent"


def test_chat_past_the_cap_gets_the_canned_redirect(client, monkeypatch):
    session_id = _reach_dsa(client, monkeypatch)
    for _ in range(MAX_CHATS_PER_QUESTION):
        resp = client.post(
            f"/api/session/{session_id}/answer", json={"transcript": "thinking aloud"}
        )
        assert resp.status_code == 200

    capped = client.post(
        f"/api/session/{session_id}/answer", json={"transcript": "one more thing"}
    )

    assert capped.status_code == 200
    assert capped.json()["reply"] == CHAT_CAP_REMARK
    assert capped.json()["dsa"]  # still on the question, still not advanced
