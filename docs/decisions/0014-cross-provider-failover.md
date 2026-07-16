# ADR 0014: Cross-provider failover — Groq primary, Gemini fallback

Date: 2026-07-16 · Status: accepted

## Context

Two free tiers with genuinely separate quotas are configured (ADR 0002):
Groq is token-bound (~100K/day ≈ 3 interviews, TPM the binding limit per
ADR 0011's measurements) and Gemini is request-bound (1,500/day ≈ 55
interviews). Yet a single Groq 429 today costs the Candidate a retryable
503 on a Turn, or an `unscored` question in an Evaluation — even while
Gemini sits idle.

## Options

1. Status quo: one provider per process, 503/degrade on failure.
2. Pool several free-tier accounts of one provider — rejected: a ToS
   violation, and one provider outage still takes everything down.
3. A failover composite across the two configured providers.

## Decision

Option 3. `FailoverProvider` wraps Groq (primary) and Gemini (secondary)
behind the same `LLMProvider` Protocol; `get_provider()` builds the chain
when both keys are set. No caller changes.

Failover fires **only** on `ProviderUnavailableError`. A malformed reply
is a deterministic parse failure, not an outage: retrying it on a
different model masks real bugs, double-bills quota, and every caller
already has malformed-recovery semantics (ADR 0013).

## Consequences

- A Groq rate limit now degrades invisibly instead of surfacing as a 503,
  as long as Gemini has quota. Both down → the ADR 0013 behavior is
  unchanged (503 on Turns, `unscored` on Scores).
- Failover is stateless and per-call: the primary is tried first on every
  call. On fast failures (429, refused connection — the measured common
  case) the retry adds negligible latency and recovery is automatic the
  moment the primary is healthy. If the primary ever *hangs* instead of
  failing fast, every call waits out the 30 s httpx timeout before the
  secondary rescues it — unusable in an interview. Accepted knowingly:
  never observed on these tiers; a sticky circuit breaker is the named
  fix if a real hang ever shows up.
- A Session can mix graders mid-Evaluation if failover fires between
  Scores; per-Dimension averages may skew across graders. Accepted for
  now; pinning an Evaluation to one provider is the named upgrade if it
  shows in practice.
- Transcription does not fail over — Gemini has no Whisper endpoint;
  `POST /api/transcribe` stays Groq-only (ADR 0010).
- The health endpoint reports the chain (`"groq+gemini"`), which is also
  how the demo signals that failover is armed.
- Secondary quota is consumed silently. Fine at demo traffic; a metrics
  day can count failovers if it matters.
- The evaluator's fan-out (ADR 0011) amplifies a Groq outage into a burst on
  Gemini: all ~9 concurrent `score_answer` calls fail over simultaneously
  during a single Evaluation, plus the `assess_session` call. Correct
  (Gemini's 1,500/day request budget absorbs it easily) but worth naming —
  it is the concrete shape of "mixed graders" above, not a separate risk.
