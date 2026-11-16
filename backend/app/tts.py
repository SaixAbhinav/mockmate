"""Text-to-speech via Edge-TTS (ADR 0004): free, no key, decent voices.

Best-effort (ADR 0036): Edge-TTS is an unofficial endpoint that is slow and
sometimes refuses requests, especially from cloud IPs. A reply that cannot be
spoken in time is returned as text only (empty audio) rather than failing the
Turn, so the interview keeps going.
"""

import asyncio
import logging
import os

import edge_tts

logger = logging.getLogger(__name__)

# Allowlist shown as the frontend voice picker. Keys are Edge-TTS voice ids.
VOICES = {
    "en-IN-NeerjaNeural": "Neerja — Indian English, female",
    "en-IN-PrabhatNeural": "Prabhat — Indian English, male",
    "en-US-AriaNeural": "Aria — American, female",
    "en-US-GuyNeural": "Guy — American, male",
    "en-GB-SoniaNeural": "Sonia — British, female",
    "en-AU-WilliamNeural": "William — Australian, male",
}

DEFAULT_VOICE = "en-AU-WilliamNeural"

DEFAULT_TIMEOUT_SECONDS = 8.0


def timeout_seconds() -> float:
    """How long a reply may take to synthesise before it goes out as text only.

    Parsed defensively, like the runner's timeout: a typo in a deploy variable
    must not make every Turn fail.
    """
    raw = os.environ.get("TTS_TIMEOUT_SECONDS", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


async def _stream(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


async def synthesize(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """MP3 bytes for the text in the given (allowlisted) voice, or b"" when the
    speech service fails or is too slow (ADR 0036). Never raises."""
    if voice not in VOICES:
        voice = DEFAULT_VOICE
    try:
        return await asyncio.wait_for(_stream(text, voice), timeout=timeout_seconds())
    except Exception as exc:  # noqa: BLE001 - any TTS failure degrades to text
        # Logged here because nothing else will notice: the Candidate still
        # gets the reply as text. The message, never the text being spoken.
        logger.warning("tts unavailable, replying without audio: %s: %s", type(exc).__name__, exc)
        return b""
