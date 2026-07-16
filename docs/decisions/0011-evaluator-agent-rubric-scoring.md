# ADR 0011: Evaluator agent — batch fan-out scoring on a generic rubric

Date: 2026-07-15 · Status: accepted

## Context

Wrap-up deliberately does no scoring (ADR 0006); the evaluator was deferred to its own
day. A Session finishes with a set of completed questions and no assessment. The product
goal is scoring against rubrics and, later, targeting weak areas — so the output must be
structured data, not just prose.

## Options

1. Per-question curated rubrics in the YAML bank (ADR 0003 anticipates them) — most
   grounded, but needs a rubric authored for every question plus a schema change.
2. Generic fixed Dimensions, anchored by each question's existing `follow_up_hints`.
3. Free-form LLM judgment with no anchor — cheapest, least consistent.

On shape: batch after the Session ends, or score incrementally each Turn.

## Decision

Option 2, batch at the end. Dimensions are `correctness`, `depth`, `clarity`, each an
integer 1–5, plus a one-sentence comment; the question bank schema is unchanged.

**The anchor is a reframing, not a reuse.** `follow_up_hints` are imperative
instructions to the *interviewer* ("Ask about train vs validation loss curves"). Handed
to an evaluator as "what a strong answer covers", they invite the model to penalise a
Candidate for not *asking* about loss curves. The evaluate prompt therefore states what
they are — interviewer notes naming topics a strong answer touches — and instructs the
model to judge topic coverage and never to reward or penalise asking. The honest limit:
the hints describe *depth cues*, not truth, so `depth` is the best-calibrated Dimension
and `correctness` the weakest. Option 1 remains the upgrade path and would not change
this graph's shape.

The evaluator is a **second LangGraph `StateGraph`**. It fans out one concurrent Score
per answered question via `Send`, gathers them with an `operator.add` reducer, then makes
one `assess_session` call. A batch fan-out does not strictly need a graph; building it as
one keeps the agents symmetric and exercises map-reduce, which the interviewer's
pure-branching graph never used.

Scoring stays **off the conversational critical path**: it runs only when
`GET /api/session/{id}/evaluation` is called on a finished Session. The Evaluation is
cached per Session behind a per-Session lock — the cache check straddles an `await`, and
the frontend's `<StrictMode>` double-invokes effects, so without the lock every Session
in dev would be scored twice.

**Unanswered questions** (`answered: false`) are not scored and are excluded from the
Dimension averages — you cannot rate the correctness of nothing. Instead the Evaluation
reports **Coverage** (`answered N of M`). Without Coverage, answering "I don't know" to
five of seven questions produces a *better* average than attempting all seven, and
"skipped everything on transformers" would read as *no weakness on transformers* —
inverting the data that weak-area targeting will consume.

**Measured, not guessed.** Probing the real Groq key with 8 concurrent evaluator-shaped
calls: zero 429s, 2,616 ms wall clock, `x-ratelimit-limit-tokens: 12000` with ~1,900
consumed. TPM is the binding limit, not concurrency: one Evaluation costs ~2,400 of
12,000 TPM, leaving room for roughly five Evaluations a minute. So **no concurrency cap**
— and a per-Evaluation semaphore would have been the wrong shape anyway, since the real
exposure is *concurrent Candidates* (ADR 0001), which a per-Evaluation cap cannot touch.
The mitigation for that is ADR 0013's graceful degradation. A global rate limiter belongs
to whichever day makes the demo genuinely public.

**Robustness**, mirroring ADR 0006: a failed Score — malformed *or* unavailable
(ADR 0013) — marks that one question `unscored` and the Evaluation still renders; a
failed assessment falls back to a neutral line. One bad response never sinks the whole
Evaluation.

## Consequences

- Structured per-question Scores exist from day one, so weak-area targeting slots in
  later without a rewrite.
- Scores are only as grounded as `follow_up_hints`, which describe depth rather than
  truth; per-question rubrics remain the upgrade path.
- Evaluations are in-memory and die with the Session (ADR 0007), consistent with
  anonymous Sessions until accounts land (ADR 0009). `_evaluations` and
  `_evaluation_locks` inherit the same deferred-cleanup debt as `_sessions`.
- Latency: roughly two calls' wall-clock (N parallel Scores + 1 assessment), paid once
  at the end rather than on every Turn.
- The Evaluation is read, never spoken; the Wrap-up remains the last thing a Candidate
  hears.
