# ADR 0017: DSA round part 2 — submit, react, and discuss through the graph

Date: 2026-07-17 · Status: accepted

## Context

ADR 0016 gave the DSA round its bank and its sandboxed runner. This ADR
records how the round joins the interview: how questions reach the queue,
how a Submission happens, and who talks when.

## Decision

Two DSA questions join the staged queue at Session creation (`stage:
"dsa"` tags, ADR 0012's queue-tag design) — a Session is now
intro → warm-up → 2 coding questions → wrap-up, 6 questions with the
curated warm-up.

**Run vs. submit.** `POST .../dsa/run` executes the tests and returns
results — no LLM, no state change, unlimited iteration. `POST
.../dsa/submit` is once per question: run, then a spoken reaction from the
new `react_to_code` provider method (one honest sentence about the
results, one question about the approach, never the corrected solution),
then the Submission — code, status, pass counts — is attached to the
question and flows onto the completed record. State mutates only after
the reaction succeeds, so a provider 503 costs nothing and Submit is
simply pressed again (the ADR 0015 posture).

**The discussion reuses the Day 2 graph.** The code and test summary enter
the transcript as the Candidate's turn, the reaction follows, phase
becomes `probing`, and spoken replies flow through the normal judge /
probe / clarify / advance machinery with the existing follow-up budget.
No new graph nodes.

**`/answer` returns 409 while a DSA question has no Submission** — today
the editor is the only way to answer a coding question. Voice-while-coding
is Day 6's watching interviewer, which will relax this guard.

**The Evaluation excludes `stage == "dsa"` records** like the intro: the
rubric scores spoken answers, and ADR 0012 defers DSA scoring. The
Submission stays on the record as the future scoring day's raw material.

## Consequences

- Session length grows to 6 (or 5 with generated warm-ups); the
  progress denominator stays fixed at creation (ADR 0015's argument).
- Submitted code enters the transcript once, capped at 10,000 chars at
  the endpoint — the judge's probes are grounded in the real code, at a
  bounded TPM cost (the resume-cap reasoning, ADR 0015).
- One Submission per question keeps reactions unfarmable and gives the
  future scoring day one unambiguous artifact per question. Re-running
  before submitting is the iteration path.
- The scripted no-key demo survives: the runner is local, and the
  scripted reaction asks about the approach without claiming a result.
