import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers import ProviderUnavailableError


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
    assert data["total_questions"] == 4  # intro + 3 warm-up (ADR 0012)


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


def test_full_session_reaches_done(client):
    session_id = client.post("/api/session", json={"domain": "ml_genai"}).json()["session_id"]
    phase = "advancing"
    for _ in range(20):
        if phase == "done":
            break
        data = client.post(
            f"/api/session/{session_id}/answer", json={"transcript": "answer"}
        ).json()
        phase = data["phase"]
    assert phase == "done"


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
    for _ in range(20):
        data = client.post(
            f"/api/session/{session_id}/answer", json={"transcript": "answer"}
        ).json()
        if data["phase"] == "done":
            break
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
        for _ in range(20):
            data = (await ac.post(f"/api/session/{sid}/answer", json={"transcript": "a"})).json()
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

    assert data["total_questions"] == 3  # intro + the 2 generated questions
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
    assert data["total_questions"] == 4  # intro + 3 curated
    assert data["warm_up_source"] == "bank"  # degradation is labeled, never silent
