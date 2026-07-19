# ADR 0018: Watching interviewer part 1 — snapshots, the Offer, and the check-in policy

Date: 2026-07-18 · Status: accepted

## Context

ADR 0012 defined the watching interviewer: during the DSA round the
frontend sends code snapshots on typing pauses, and on an interval
(~60–90 s, with cooldowns) the backend has the LLM look at the latest
snapshot and decide stay silent / ask / hint, with hints when snapshots
show no progress. This ADR records the mechanics: how the backend sees
the code, when it may take an LLM look, and what shape the decision has.
The conversational half (voice while coding) is ADR 0019.

## Decision

**The frontend drives the clock; the backend owns the policy.** No
websockets or background tasks — the app stays request-driven (ADR 0007
posture). `POST .../dsa/snapshot` stores the latest code on typing pauses
(no LLM). The frontend polls `POST .../dsa/check-in` (~25 s); the
backend's gates decide what a poll becomes. Poll frequency is a client
detail; the policy is server-enforced, so a misbehaving client cannot
farm LLM calls.

**Two clocks.** The first Snapshot stamps `typing_started_at`; the first
LLM look becomes due 75 s after *typing starts* — reading the problem is
never watched, and a false `stuck` signal at 75 s was the
naggy-interviewer failure mode. The question's own clock drives the
**Offer**: a Candidate who has typed nothing for 120 s gets a
deterministic canned invitation to ask for clarification — no LLM call,
at most once per question. It counts as an interjection (cooldown, cap)
but not as a Hint: it offers help without giving any. Because it is
deterministic it also works in the keyless scripted demo. After it, the
normal machinery takes over — the still-frozen Candidate's first LLM
look lands ~90 s later with a genuinely true stuck flag.

**Recurring gates:** ≥75 s between looks, ≥90 s after any interjection,
at most 3 interjections per question — then silence for good.

**Watch state lives on the current question** (`current_question["watch"]`,
like `submission`) — it resets itself when the interview advances. Only
the latest snapshot is kept, plus the code seen at the last look. Counts
(interjections, hints, chats, runs) ride the completed record for the
future DSA-scoring day.

**Stuck is computed in code, decided by the LLM.** Stuck =
whitespace-insensitive equality between the current code and the code at
the watcher's last look (starter code before the first). It enters the
prompt as a signal; the model still chooses silent/ask/hint, with hints
reserved for stuck candidates and dictating the solution forbidden.
Because equality misses the *churning* candidate (code keeps changing,
tests keep failing), `/dsa/run` notes run telemetry on the watch —
{runs, last_passed, last_total} — and the prompt receives a run summary.
This respects ADR 0017's boundary: a run still causes no interview
movement; it leaves a note for a watcher that did not exist then.
(Judging every snapshot was rejected in ADR 0012 as too expensive; fully
deterministic interjections were rejected as robotic — the Offer is the
one exception, because that situation needs no judgment.)

**A Check-in never fails loudly.** `watch_code` returns strict JSON
`{action, remark}`; malformed and unavailable both collapse to silent
(logged per ADR 0013) — a poll must never surface a 503 mid-thought. The
look is still recorded, so a failing provider is not hammered every 25 s.
The scripted provider is always silent apart from the Offer.

## Consequences

- Interjections join the transcript, so the submit reaction (ADR 0019)
  and the discussion probes are grounded in what was already said; they
  consume no probe/clarify follow-up budget.
- Quota stays bounded: ~1 LLM call per 75+ s of coding, capped at 3
  interjections per question; the Offer costs nothing.
- Polling costs ~2 requests/min while coding — fine locally; worth a
  revisit on the public-hardening day.
- The clock is `time.monotonic` behind a patchable module hook; the
  policy is pure functions, so cooldown rules are one-line unit tests.
