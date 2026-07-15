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
    assert 6 <= data["total_questions"] <= 8


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
