# ADR 0004: Voice stack — browser Web Speech API (STT) + Edge-TTS (output)

Date: 2026-07-12 · Status: accepted

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
