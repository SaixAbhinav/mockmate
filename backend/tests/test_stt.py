"""Speech-to-text transport (ADR 0010, ADR 0026).

The request Groq receives is asserted directly: the vocabulary digest only helps
if it actually reaches the API as the `prompt` field.
"""

import httpx
import pytest

from app.stt import SttUnavailableError, transcribe

pytestmark = pytest.mark.anyio


@pytest.fixture
def captured(monkeypatch):
    """Capture the outgoing request instead of calling Groq."""
    seen = {}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, files=None, data=None):
            seen["url"] = url
            seen["files"] = files
            seen["data"] = data
            return httpx.Response(
                200, json={"text": "  a transcript  "}, request=httpx.Request("POST", url)
            )

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr("app.stt.httpx.AsyncClient", FakeClient)
    return seen


async def test_transcribe_returns_stripped_text(captured):
    assert await transcribe(b"audio", "answer.webm", "audio/webm") == "a transcript"


async def test_transcribe_sends_no_prompt_by_default(captured):
    await transcribe(b"audio", "answer.webm", "audio/webm")
    assert "prompt" not in captured["data"]


async def test_transcribe_forwards_the_vocabulary_digest(captured):
    await transcribe(b"audio", "answer.webm", "audio/webm", prompt="Sai Abhinav, SmartSignal")
    assert captured["data"]["prompt"] == "Sai Abhinav, SmartSignal"


async def test_transcribe_omits_a_blank_prompt(captured):
    # A Candidate with no resume has no digest; an empty prompt field is noise.
    await transcribe(b"audio", "answer.webm", "audio/webm", prompt="   ")
    assert "prompt" not in captured["data"]


async def test_transcribe_without_a_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SttUnavailableError):
        await transcribe(b"audio", "answer.webm", "audio/webm")
