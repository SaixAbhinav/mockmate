"""Speech-to-text, server-side (ADR 0004, amended).

Browser Web Speech API turned out to depend on the browser vendor's cloud
service (opaque "network" errors, unsupported browsers), so audio is now
recorded in the browser and transcribed here via Groq's free-tier Whisper.
"""

import os

import httpx


class SttUnavailableError(Exception):
    """Raised when no STT backend is configured."""


async def transcribe(audio: bytes, filename: str, content_type: str) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise SttUnavailableError(
            "Voice input needs a GROQ_API_KEY in backend/.env (free at "
            "console.groq.com). The text box works without it."
        )
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (filename, audio, content_type)},
            data={"model": "whisper-large-v3-turbo", "language": "en"},
        )
        resp.raise_for_status()
        return resp.json()["text"].strip()
