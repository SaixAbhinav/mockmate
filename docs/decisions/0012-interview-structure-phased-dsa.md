# ADR 0012: Interview structure — phased session with a resume warm-up and a DSA round

Date: 2026-07-15 · Status: accepted

## Context

The interview today is a single phase: a queue of 6–8 curated domain
questions with probe/clarify/advance (ADR 0006). The target product is a
realistic technical interview: the candidate introduces themselves, the
interviewer probes their background, then the interview shifts to a live
coding round where the interviewer watches the code, asks about it, and
helps when the candidate is stuck. This ADR fixes the target structure and
splits the work into build days; each day still gets its own plan and ADRs
for the decisions it opens up.

## Decision

The interview becomes one phased Session that **replaces** the current
flow (not a second mode alongside it):

`intro → warm_up → dsa → done`

- **Intro** — the interviewer opens with "tell me about yourself"; the
  candidate answers by voice as today.
- **Warm-up** — 2–3 questions probing the candidate's skills, projects,
  and experience, LLM-generated from an **uploaded resume** (PDF/text),
  but executed through the existing probe/clarify/advance graph so the
  Day 2 judging machinery is reused, not rebuilt. With no resume or no API
  key, the warm-up falls back to curated domain-bank questions (ADR 0008),
  preserving the zero-setup scripted demo (ADR 0002).
- **DSA round** — 2 random questions from a new curated DSA bank (YAML,
  ADR 0008 style, extended with function signature, starter code, and test
  cases), drawn one easier + one harder. The candidate writes **Python
  only** in an in-app editor and runs it against the question's test cases
  in a sandboxed subprocess (timeout, no network). A subprocess is a
  guardrail for a self-hosted tool, not a hard security boundary; container
  isolation is a later hardening day. Pass/fail results feed the
  interviewer, who reacts, probes the approach, and advances.
- **The watching interviewer** — during the DSA round the frontend sends
  code snapshots on typing pauses; on an interval (~60–90 s, with
  cooldowns) the backend has the LLM look at the latest snapshot and decide
  *stay silent / ask about the code / offer a hint*, with hints triggered
  when snapshots show no progress. Every snapshot being judged was rejected
  as too expensive on free-tier rate limits; candidate-action-only was
  rejected as losing the "interviewer is watching" feel.

## Build days

- **Day 4 — phased Session + resume warm-up.** Phase machine, resume
  upload and text extraction, resume-grounded warm-up through the existing
  graph. DSA phase stubbed (session wraps after warm-up). New dependency
  to flag: a PDF text extractor (`pypdf`).
- **Day 5 — DSA round.** DSA question bank, code editor pane (new frontend
  dependency to flag: CodeMirror), run-against-tests subprocess runner,
  interviewer reaction/probing on submit. If this proves too big in its own
  planning session, the split is editor + bank + submit first, execution
  runner second.
- **Day 6 — the watching interviewer.** Snapshots, interval check-ins,
  stuck detection, interjections and hints; voice stays live while coding.

## Consequences

- Day 4's phase machine is the skeleton the later days hang on; the
  riskiest slice (Day 5) doesn't also carry realtime-watching complexity.
- The domain picker's role shrinks: curated domain banks become the
  warm-up fallback rather than the whole interview.
- The Day 3 evaluator (ADR 0011) scores Q&A answers only; scoring the DSA
  round (code quality, hints used, test results) is a later day.
- Resume content enters the system for the first time — it is held in the
  in-memory Session like everything else (ADR 0007) and dies with it;
  retention decisions stay with ADR 0009.
- Code execution adds a real attack surface; until the hardening day the
  runner's subprocess limits are documented as best-effort and the app
  remains a run-it-yourself tool (ADR 0001 posture).
