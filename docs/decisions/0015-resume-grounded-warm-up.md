# ADR 0015: Resume-grounded warm-up on a staged question queue

Date: 2026-07-16 · Status: accepted

## Context

ADR 0012 fixed the target interview structure (intro → warm_up → dsa) and
scoped Day 4 to the phase machine plus the resume warm-up, DSA stubbed. It
left the implementation decisions open: how stages map onto the Day 2
graph, where resume content lives, what happens without a resume or key,
and whether the intro is scored.

## Decision

**Stages are question tags, not graph nodes.** The queue becomes
`[intro] + warm-ups`, each entry carrying `stage`; the ADR 0006 graph is
untouched. The graph routes within a question, the queue routes between
questions, and a stage is a property of a question — a stage machine
around the graph would duplicate routing the queue already does. Day 5
adds `dsa` as more tagged entries plus its own submit path.

**The intro is a fixed scripted question**, never LLM-paraphrased
(ADR 0008's verbatim rule, reapplied), judged for probe/clarify like any
other question — the interviewer probing your background is the realism
ADR 0012 wants.

**Warm-up questions are generated once, at Session creation**, from the
uploaded resume, in the ADR 0003 bank shape (topic, difficulty, question,
follow_up_hints) so probe/clarify grounding and the evaluator's rubric
anchor (ADR 0011) work on them with zero new code. The prompt forbids
inventing anything not on the resume. Generating at creation keeps the
"question 1 of 4" denominator fixed and keeps LLM calls off the
conversational critical path (ADR 0011's argument, reapplied).

**One fallback path.** `ScriptedProvider` returns an empty list; the
endpoint treats an empty list or any `ProviderError` as "draw 3 curated
questions from the domain bank" (`plan_warm_up`, which replaces the
deleted 6–8 question `plan_session`). No Session ever fails to start
because generation failed, and the zero-setup demo (ADR 0002) survives.
The fallback is **labeled, never silent**: the session response carries
`warm_up_source` ("resume" | "bank") so a Candidate who uploaded a resume
can tell whether the warm-up they got is actually grounded in it —
consistent with the repo's precedent that degradation is always visible
(`unscored` questions, the scripted wrap-up announcing itself).

**Resume handling.** `POST /api/resume` extracts plain text (pypdf for
PDF, UTF-8 passthrough for text), caps the upload at 2 MB and the text at
15,000 chars (~4K tokens, bounding the generation prompt), rejects
extractions under 200 chars (too thin to ground questions — fail honestly
at upload, before any quota is spent), and stores it
in an in-memory dict (ADR 0007 posture): anonymous, unscoped, dies with
the process. Retention decisions stay with ADR 0009. Resume text is PII —
it is never logged and never echoed into error details.

**The intro is excluded from the Evaluation.** Scoring "tell me about
yourself" on correctness 1–5 is meaningless, and a freebie in Coverage
would flatter every Session's denominator. Filtered by stage in
`evaluate_session`.

## Consequences

- A Session is 4 questions (intro + 3 warm-up) until Day 5 adds the DSA
  round — deliberately smaller than the old 6–8 domain round it replaces.
- Session creation gains one LLM call (~1–3 s) when a resume is present.
- Generated questions are only as grounded as the resume text pypdf
  extracts; a scanned-image PDF extracts nothing and is rejected upfront.
- **The judge never sees the resume.** During warm-up Turns the interviewer
  judges with the generated `follow_up_hints` as its only resume-derived
  grounding, so it cannot catch resume contradictions ("you said you never
  shipped it, but your resume says…"). Deliberate: the capped resume is
  ~4K tokens against a measured 12K TPM budget (ADR 0011), so piping it
  into every warm-up judge call would spend a third of the per-minute
  budget per Turn. A resume-aware judge is the named upgrade path if
  warm-up probing feels generic in practice.
- `_resumes` inherits the same deferred-cleanup debt as `_sessions`
  (ADR 0007).
- The domain picker's role shrinks to selecting the fallback bank and
  labeling the Session, as ADR 0012 predicted.
- A clarity-only assessment of the intro is a possible future refinement
  (it pairs naturally with a delivery-metrics day); excluding it entirely
  is today's simpler call.
