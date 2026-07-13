"""Text-to-speech via Edge-TTS (ADR 0004): free, no key, decent voices."""

import edge_tts

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


async def synthesize(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Return MP3 bytes for the given text in the given (allowlisted) voice."""
    if voice not in VOICES:
        voice = DEFAULT_VOICE
    communicate = edge_tts.Communicate(text, voice)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)
