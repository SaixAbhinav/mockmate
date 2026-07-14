# ADR 0009: Real accounts for every Candidate, with deletion, as a separate later day

Date: 2026-07-14 · Status: accepted

## Context

ADR 0001 made MockMate multi-user but left open whether public Candidates'
data (resumes, interview history) persists like the owner's personal vault
does, or is discarded per session. Grilling the project surfaced that this
was undecided and blocks nothing today only by accident.

## Decision

Persist resume + interview history for every Candidate, not just the owner
— which requires real identity, so auth is email/OAuth accounts rather than
anonymous device ids. This is explicitly **not** part of Day 2: Day 2's
sessions stay anonymous (ADR 0007), and accounts land as their own future
day/PR. Because persisting strangers' personal data indefinitely without a
way to remove it is the kind of thing that's awkward to retrofit, a basic
"delete my account and data" capability ships as part of that same future
day, not deferred further.

## Consequences

- Day 2 is unblocked; D7's in-memory session storage is designed to swap to
  account-scoped storage later rather than being built for it now.
- The future accounts day is bigger than "add a login form" — it includes
  deletion, which touches every place resume/history data is stored.
