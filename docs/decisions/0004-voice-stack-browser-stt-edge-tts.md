# ADR 0004: Voice stack — browser Web Speech API (STT) + Edge-TTS (output)

Date: 2026-07-12 · Status: amended (see bottom); STT half superseded by ADR 0010

> **Note (2026-07-14):** The STT decision below (browser Web Speech API as the
> primary path) is superseded by **ADR 0010** — Groq Whisper server-side is now
> primary, with the browser Web Speech API kept as the no-key fallback. The TTS
> decision (Edge-TTS, Neerja) and the `en-IN` locale intent still stand.

## Context

Voice from day one is a product requirement. Speech-to-text and
text-to-speech both have free-but-limited and heavy-but-controllable options.

## Options

- STT: (a) browser Web Speech API — free, zero infra, Chrome/Edge only,
  quality depends on the browser; (b) local faster-whisper — better control
  and accuracy, needs a Python inference path and adds latency work.
- TTS: (a) Edge-TTS — free Microsoft neural voices via network, no key;
  (b) local Piper — offline but flatter voices; (c) browser speechSynthesis —
  free but robotic.

## Decision

STT (a) + TTS (a): Web Speech API in the browser, Edge-TTS on the backend
(voice: en-IN-Neerja — Indian-English, matching the interviews this trains
for). faster-whisper is the designated upgrade path if browser STT quality
disappoints; the frontend already isolates STT in one function to keep that
swap small.

## Consequences

- $0, no keys, ships in the walking skeleton.
- Chrome/Edge requirement for voice input (text fallback provided).
- TTS requires network (Edge-TTS calls Microsoft's service).

## Amendment (2026-07-12, same day)

Browser STT failed in first real use: the Web Speech API silently depends on
the browser vendor's cloud speech service and returned opaque "network"
errors on the owner's machine. Replaced with **server-side STT**: the browser
records audio with MediaRecorder and uploads it to `/api/transcribe`, which
calls **Groq's free-tier Whisper** (`whisper-large-v3-turbo`) — the same key
that powers the LLM. Works in every browser; text box remains the no-key
fallback. faster-whisper (local) stays the offline upgrade path.

TTS voice also became user-selectable from an allowlist (`/api/voices`)
after the default Indian-English voice didn't suit the owner's taste —
hardcoded voice choices don't survive contact with users.
