# ADR 0010: STT — Groq Whisper primary (server-side), browser Web Speech API as no-key fallback

Date: 2026-07-14 · Status: accepted · Supersedes the STT half of ADR 0004

## Context

ADR 0004 chose the browser Web Speech API for STT, naming a Whisper path as
the upgrade "if browser STT quality disappoints." It has: browser STT
accuracy is inconsistent (especially on ML/GenAI jargon) and Chrome/Edge-only.
The walking skeleton actually shipped browser Web Speech API (matching ADR
0004) — the `plan-2026-07-14.md` claim of "MediaRecorder → Groq Whisper" was
aspirational, not what was built.

## Decision

STT goes behind an interface (same pattern as `LLMProvider`, ADR 0002):

- **Primary (keyed):** Groq Whisper, server-side. Frontend captures audio
  (MediaRecorder) and uploads it to a **standalone `POST /api/transcribe`**,
  which returns text. The text is shown to the candidate and then sent to
  `POST /api/session/{id}/answer` — so the answer endpoint stays text-only,
  identical to the typed path, and the candidate can see/correct what was
  heard before it's judged.
- **No-key fallback:** the existing browser Web Speech API path is retained,
  so the zero-setup demo (ADR 0002) keeps working voice with no key and no
  new dependency.

**Bundled into Day 2** with the interviewer agent (the answer path is being
reworked anyway).

**Explicitly deferred:** local `faster-whisper` as a no-key server-side STT.
It was considered for the no-key path but adds a heavy dependency + model
download + inference latency — too much on top of Day 2's agent + Groq
Whisper work, and latency work is a Day 2 non-goal. It becomes its own later
day, slotting into the same STT interface. This is the ADR 0004 "designated
upgrade path," now scheduled rather than hypothetical.

## Consequences

- Keyed deployments get accurate, browser-independent STT; no-key demo keeps
  free voice via the browser.
- The frontend carries two capture paths (MediaRecorder for Whisper, the
  existing SpeechRecognition for fallback) selected by whether a key/Whisper
  backend is available.
- `en-IN` locale intent (ADR 0004, Neerja TTS) carries over: Groq Whisper is
  prompted/configured for Indian-English input where supported.
