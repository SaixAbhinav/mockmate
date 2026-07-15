# ADR 0013: Provider failures — malformed replies vs unavailable providers

Date: 2026-07-15 · Status: accepted

## Context

`LLMProvider` exists so callers never learn that Groq speaks HTTP. It leaked:
`_chat_json` called `resp.raise_for_status()`, so a 429 or timeout escaped as
`httpx.HTTPStatusError`, while only parse failures became `ProviderError`.

ADR 0006 tells the interviewer: "Malformed/unknown judgment → default to `advance`
with a neutral reaction; never crash a turn." That rule was written for a model that
*replied with garbage* — advancing is a fair recovery, worst case a missed Probe.

Building the evaluator (ADR 0011) made the gap matter: it fans out several concurrent
calls, so rate limiting is plausible, and it runs last, so a crash costs the Candidate
the entire interview's payoff.

## Options

1. Catch `Exception` at each call site — works, masks real bugs, repeats itself.
2. Catch `httpx` errors at each call site — leaks transport concerns into the agents,
   defeating the interface.
3. Convert at the source and distinguish the two failure modes by type.

## Decision

Option 3, with a three-type hierarchy:

- `ProviderError` — base: the provider could not give a usable answer.
- `ProviderMalformedError` — it replied, but the reply could not be parsed.
- `ProviderUnavailableError` — it could not be reached (transport, rate limit, timeout).

Providers convert their own failures; no caller imports `httpx`.

Each caller then catches what it actually means:

- The interviewer narrows to `ProviderMalformedError` → advance. **This refines ADR
  0006 rather than contradicting it**: "never crash a turn" was about a bad reply, not
  about no reply. `ProviderUnavailableError` propagates and `/answer` returns **503**,
  so the Candidate retries. Conflating the two would silently advance past a
  Candidate's answer on a transient 429 — burning a question with nothing to show it.
- The evaluator catches the base `ProviderError`: either way, that question is
  `unscored` and the Evaluation still renders.

## Consequences

- A rate-limited Turn is a visible, retryable 503 instead of a silently burned question.
- A rate-limited Score costs one question, not the whole Evaluation — load-bearing for
  the multi-user demo (ADR 0001), where concurrent Candidates, not any single fan-out,
  are what exhaust the token budget (ADR 0011).
- Session state survives a 503: `submit_answer` returns new state and the caller only
  assigns on success, so a retry resumes cleanly.
- ADR 0006's wording is broader than its true scope; this ADR is the record of the
  narrowing, so a future reader doesn't "fix" the narrowed catch back.
- Anything logging a provider failure must log that error's own message, never
  `logger.exception` — `GeminiProvider` puts its API key in the request URL, so a
  chained httpx traceback would leak it. Moving that key to an `x-goog-api-key` header
  is a known follow-up.
