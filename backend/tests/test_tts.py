import asyncio
import logging

import pytest

from app import tts

pytestmark = pytest.mark.anyio


class FakeCommunicate:
    """Stands in for edge_tts.Communicate; `behaviour` decides what stream() does."""

    behaviour = "ok"
    seen = {}

    def __init__(self, text, voice):
        FakeCommunicate.seen = {"text": text, "voice": voice}

    async def stream(self):
        if FakeCommunicate.behaviour == "fail":
            raise RuntimeError("403, message='Invalid response status'")
        if FakeCommunicate.behaviour == "slow":
            await asyncio.sleep(5)
        yield {"type": "WordBoundary"}
        yield {"type": "audio", "data": b"mp3-"}
        yield {"type": "audio", "data": b"bytes"}


@pytest.fixture(autouse=True)
def fake_edge_tts(monkeypatch):
    FakeCommunicate.behaviour = "ok"
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)


async def test_synthesize_joins_the_audio_chunks():
    assert await tts.synthesize("Hello", "en-US-AriaNeural") == b"mp3-bytes"
    assert FakeCommunicate.seen == {"text": "Hello", "voice": "en-US-AriaNeural"}


async def test_unknown_voice_falls_back_to_the_default():
    await tts.synthesize("Hello", "not-a-voice")
    assert FakeCommunicate.seen["voice"] == tts.DEFAULT_VOICE


async def test_a_failing_speech_service_returns_no_audio_instead_of_raising(caplog):
    FakeCommunicate.behaviour = "fail"

    with caplog.at_level(logging.WARNING, logger="app.tts"):
        assert await tts.synthesize("Hello") == b""

    # The failure must be visible in the logs: it is otherwise silent (ADR 0036).
    assert "RuntimeError" in caplog.text


async def test_a_slow_speech_service_times_out_with_no_audio(monkeypatch, caplog):
    FakeCommunicate.behaviour = "slow"
    monkeypatch.setenv("TTS_TIMEOUT_SECONDS", "0.05")

    with caplog.at_level(logging.WARNING, logger="app.tts"):
        assert await tts.synthesize("Hello") == b""

    assert "TimeoutError" in caplog.text


@pytest.mark.parametrize("raw,expected", [("", 8.0), ("2.5", 2.5), ("soon", 8.0), ("-1", 8.0)])
def test_timeout_is_read_defensively(monkeypatch, raw, expected):
    monkeypatch.setenv("TTS_TIMEOUT_SECONDS", raw)
    assert tts.timeout_seconds() == expected
