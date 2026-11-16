# ADR 0036: The interviewer's voice is best-effort

Date: 2026-11-15 · Accepted: 2026-11-15 · Status: accepted · Amends [0004](0004-voice-stack-browser-stt-edge-tts.md)'s TTS half

## Context

ADR 0004 chose Edge-TTS for speech: free, no key, good voices. It is also an
unofficial endpoint, and in November 2026 it failed two ways in production:

- **Refusals.** Microsoft began rejecting edge-tts 7.2.8 with HTTP 403. Every
  Turn synthesises its reply before responding, so `POST /api/session` returned
  500 and nobody could start an interview. Upgrading to 7.3.1 (PR #62) fixed
  the outright block, but after the upgrade the live site still failed about
  half of answers and submissions: the LLM call succeeded (`ok=True` in the
  logs) and the request then failed at the speech step.
- **Latency.** Synthesis of one reply took 1 to 19 seconds when measured
  locally, and 8 seconds on Lambda. API Gateway gives up after about 30 seconds.

Text is what the interview actually needs: the transcript already shows every
reply, and the text box already works without a microphone (ADR 0010). Losing
a reply's audio is a degraded Turn. Losing the Turn ends the interview.

## Decision

Speech is optional on every reply.

- **`synthesize` never raises.** Any failure, or taking longer than
  `TTS_TIMEOUT_SECONDS` (default 8, parsed defensively), returns empty audio,
  and the endpoint sends the reply with `audio_b64: ""`. No endpoint changes:
  `base64("")` is already `""`.
- **The failure is logged.** The exception's type and message are logged at
  WARNING, never the text being spoken. A silent fallback would otherwise
  leave nothing for anyone to notice.
- **The frontend treats missing audio as silence.** `playAudio` goes straight
  to idle when there is no audio, and treats a browser refusing to play as
  silence rather than an error banner.

## Consequences

- One flaky dependency can no longer end a Session. A speech outage turns the
  product into a text interview until it recovers.
- A Candidate may hear some replies and not others in the same Session. That
  is accepted: the text is always there.
- The 8-second cap bounds how long the slowest Turn can wait on speech, at the
  cost of dropping audio for a slow-but-successful synthesis.
- How often audio is dropped is visible as `tts unavailable` warnings in
  CloudWatch, which is the signal to revisit the provider.

## Alternatives considered

- **Retry synthesis.** Rejected: it doubles the worst-case latency, and the
  measured failures came with multi-second delays already.
- **Switch to a paid TTS API.** Deferred, not rejected: it contradicts ADR
  0002's free-to-run goal. The warning count above is what would justify it.
- **Synthesise in the browser (Web Speech API).** Rejected for now: voices
  differ per browser and OS, the same unevenness that moved STT server-side in
  ADR 0010.
