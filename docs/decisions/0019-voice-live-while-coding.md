# ADR 0019: Watching interviewer part 2 — voice stays live while coding

Date: 2026-07-18 · Status: accepted

## Context

ADR 0017 made `/answer` return 409 during an unsubmitted DSA question
("today the editor is the only way to answer"), explicitly marked for
Day 6 to relax. ADR 0012's target is an interviewer you can talk to
while coding. This ADR records what replaces the guard.

## Decision

`/answer` during an unsubmitted DSA question becomes a **side
conversation**, not a judged answer: the new `coding_chat` provider
method replies to the utterance, grounded in the question and the latest
Snapshot; both turns join the transcript; and nothing else moves — no
judge call, no phase change, no queue movement, no follow-up budget.
The Submission remains the only way past a coding question, so the state
machine stays exactly as honest as the 409 kept it.

**Chat is capped at 15 exchanges per question.** Because chat advances
nothing, nothing structural bounds it — uncapped, it would be the app's
only unmetered LLM surface (free-tier token math makes one chatty
candidate a real cost). Past the cap the reply is a canned spoken
redirect with no LLM call — the same generous-cap-graceful-ceiling shape
as the follow-up budget and the interjection cap.

**`react_to_code` now receives the transcript.** Day 5's
history-free signature was sound only because the 409 guaranteed nothing
was said between question and Submission. With a watcher that can hint
first, a history-blind reaction produces the worst possible seam: asking
the candidate to justify an approach the interviewer itself suggested.
The prompt now acknowledges its own hints instead.

The chat prompt answers clarifying questions and acknowledges thinking
aloud but never dictates the solution — the react_to_code posture. The
scripted provider returns a canned line, keeping the no-key demo's voice
loop alive through the coding round.

Chat is user-initiated, so provider failure is a 503 with the Session
untouched (the `/answer` posture) — deliberately unlike Check-ins
(ADR 0018), which are automated polls and fail silent.

## Consequences

- The 409-dependent tests become chat tests; the drive-to-done helpers
  detect a waiting coding question via the `dsa` payload instead of the
  409. The protected intent — talking cannot pass a coding question —
  survives as "chat never advances".
- Thinking aloud enters the transcript, giving the judge richer
  grounding for post-submit probes; the future scoring day can decide
  what rambling is worth. Chat counts ride the completed record.
- One LLM call per utterance while coding, on the Candidate's own
  action, bounded at 15 per question.
