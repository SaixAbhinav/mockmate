# ADR 0028: A chat reply starts the Watcher's cooldown

Date: 2026-07-27 · Accepted: 2026-07-27 · Status: accepted

## Context

ADR 0018 gave the Watcher a 90-second cooldown between Interjections so the
Interviewer "cannot hover". At the time there was exactly one way for the
Interviewer to speak during the coding round: the Watcher choosing to.

ADR 0019 then made voice live while coding, adding a second way — answering the
Candidate. That path was never wired into the cooldown:

- `note_chat` increments `chats` and touches nothing else.
- `check_in_due` gates on `last_spoke_at`, which only `note_interjection` sets.

So the Interviewer could answer a Candidate's question and then interject
unprompted moments later — the hovering failure mode ADR 0018 exists to prevent,
reached through a path that postdates it. Reproduced end-to-end: with a look due
by the interval, a chat reply followed immediately by a poll returns `hint`
where it should return `silent`.

The frontend skips polls while the turn is not idle (`App.jsx`), which narrows
the window without closing it — and ADR 0018 is explicit that the policy is
server-enforced precisely so a client cannot be relied on for it.

There is a second, smaller hole on the same path. The canned redirect past the
15-chat cap (ADR 0019) speaks to the Candidate but records *nothing at all*:
`note_chat` is only called on the branch that made an LLM call.

Found while writing ADR 0027 and recorded there as deliberately unfixed, so that
the relocation could stay behaviour-preserving. This ADR is that fix.

## Decision

**Whenever the Interviewer speaks during the coding round, the Watcher's
cooldown starts.**

- `note_reply(watch, now)` sets `last_spoke_at` and nothing else.
- It is called on **both** chat branches — including the capped redirect, which
  is still the Interviewer talking.
- **A reply is not an Interjection.** It costs nothing from
  `MAX_INTERJECTIONS_PER_QUESTION` and is never counted as a Hint. The Candidate
  asked for it; the cap exists to bound what the Interviewer does *unprompted*.
- The Provider-failure path is untouched: a chat that 503s stamps nothing,
  because nothing was said.
- The stamp is taken after the reply is produced rather than at the top of the
  turn, since the LLM call sits in between and the cooldown should run from when
  the Candidate is actually spoken to.

## Consequences

- **A Candidate in active conversation suppresses unprompted Check-ins for as
  long as they keep talking.** This is the intended reading, not a side effect:
  someone already in dialogue with the Interviewer does not also need it
  breaking in. It is bounded by ADR 0019's 15-chat cap, and past the cap the
  redirect still stamps, so the ceiling holds rather than inverting.

- **Slightly fewer Provider calls.** `check_in_due` short-circuits on the
  cooldown before any look is taken, so a suppressed Check-in costs no LLM call
  at all.

- **Interjections can land later in a question.** Fifteen well-spaced chats
  could push the Watcher's three interjections toward the end. Acceptable: a
  question where the Candidate is talking that much is not one where the
  Interviewer needs to volunteer more.

- **Nothing in ADR 0018 or 0019 is reversed.** This applies 0018's existing rule
  to a speaking path 0019 introduced; both ADRs keep their decisions.

## Alternatives considered

- **Count a chat toward the interjection cap.** Rejected: the cap bounds
  *unprompted* remarks. A talkative Candidate would spend the Watcher's three
  interjections without it ever having chosen to speak, silencing it for the
  rest of the question — a worse failure than the one being fixed.

- **A shorter, separate post-chat cooldown.** Rejected: there is no evidence
  justifying a second constant, and one cooldown is easier to reason about than
  two that interact.

- **Also reset the look interval (`last_check_at`).** Rejected as redundant. The
  interval governs how often the Watcher *looks*; the cooldown already prevents
  speaking, and `check_in_due` checks the cooldown first, so no look happens
  anyway.

- **Do nothing and rely on the frontend's idle gate.** Rejected on ADR 0018's
  own grounds: the policy is server-enforced so that client behaviour cannot
  farm or suppress it.

## Status

Accepted and implemented. Verified by reproduction rather than assertion: both
new end-to-end tests fail on the unfixed code with exactly the bug's signature
(`hint` where `silent` belongs), and pass with `note_reply` wired in. Unit tests
cover the cooldown start and the not-an-Interjection rule.
