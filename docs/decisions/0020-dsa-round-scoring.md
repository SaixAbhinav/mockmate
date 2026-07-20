# ADR 0020: DSA-round scoring — measured facts, judged quality

Date: 2026-07-20 · Status: accepted

## Context

ADR 0012 deferred scoring the DSA round to its own day and named its
inputs: code quality, hints used, test results. Since Day 6 every
completed DSA record carries them — the Submission ({code, status,
passed, total}) and the watch counts ({interjections, hints, chats,
runs}) — while the evaluator filtered DSA records out entirely. The
speech rubric (correctness/depth/clarity, ADR 0011) does not fit code:
a code answer's correctness is already measured by the Runner, and its
"clarity" means something different from speech.

## Decision

**A separate DSA section, not a merged rubric.** The Evaluation gains a
`dsa` block — per-question entries plus aggregates (mean per code
Dimension, total hints used). Spoken averages and Coverage are
untouched: mixing differently-anchored scores skews the average, and
changing Coverage's denominator would silently re-grade every Session.

**Tests decide correctness; the model never re-judges it.** Each entry
carries the Submission's {status, passed, total} verbatim — no LLM call,
no 1–5 mapping (a mapped number would fake precision the Runner never
claimed). A new provider method, `evaluate_submission`, judges what
tests cannot: `code_quality` (readable, idiomatic, edge-case-aware
Python) and `approach` (sound algorithm, and how well the Candidate
explained and defended it in the post-submission discussion), each 1–5
with one comment, strict JSON. Because the facts are computed, the
keyless scripted demo shows real pass/fail — only the judgment is
canned.

**Hints and runs are context, never a penalty.** The watch counts enter
the prompt with an explicit no-mechanical-penalty instruction and are
reported as facts. A -1-per-hint rule would punish exactly the
Candidates who used the watching interviewer as designed. (Rejected:
scoring correctness by LLM — it can only contradict the Runner;
merging DSA into the spoken rubric — skew; arithmetic hint penalties —
misaligned incentives.)

**One graph, two fan-outs.** `plan_evaluation` routes DSA records to a
`score_submission` node dispatched alongside `score_answer`; both feed
the same reducer (DSA entries tagged `kind: "dsa"`) and the same
`assess` join, which therefore still runs once. The assessment prompt
receives coding lines, so the prose can mention the code. A DSA record
with a Submission is scored even if the discussion left
`answered: false` — the code is what was submitted, and a poor defense
shows up in `approach`. The impossible-by-construction record without a
Submission degrades to a skipped entry with no LLM call.

**Failure keeps the facts.** A failed `evaluate_submission` marks only
the judged half `unscored`; the entry still renders its test facts and
counts. Retryable semantics are inherited from ADR 0011/0013 unchanged:
unavailable → not cached, malformed → cached.

## Consequences

- Every Stage now feeds the Evaluation; the "hints used" input ADR 0012
  promised the scoring day is live.
- Two more LLM calls per Evaluation (one per DSA question, ~600 tokens
  each); the ADR 0011 capacity math absorbs this without a new limit.
- The code Dimensions are only as grounded as one model call over one
  file of code — per-question rubrics (ADR 0011's upgrade path) would
  apply here too.
- Weak-area targeting gains structured code data without a rewrite,
  same as the spoken Scores did on Day 3.
