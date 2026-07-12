"""Text-to-speech via Edge-TTS (ADR 0004): free, no key, decent voices."""

import edge_tts

# Indian-English voice — the interviews this trains for happen in this accent.
VOICE = "en-IN-NeerjaNeural"


async def synthesize(text: str) -> bytes:
    """Return MP3 bytes for the given text."""
    communicate = edge_tts.Communicate(text, VOICE)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)
