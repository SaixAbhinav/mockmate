# ADR 0007: Session state — in-memory behind an interface

Date: 2026-07-14 · Status: accepted

## Context

The interviewer agent (ADR 0006) needs somewhere to keep session state
(question queue, phase, probe/clarify count) between turns. Options: an
in-memory dict, or SQLite via a LangGraph checkpointer now.

## Decision

In-memory dict behind a small interface, mirroring the `LLMProvider` pattern
(`backend/app/providers.py`). Sessions are anonymous for now (ADR 0009 defers
accounts to a later day); a session dying on backend restart is acceptable
at this stage.

## Consequences

- Swapping to SQLite later — needed once accounts (ADR 0009) make sessions
  Candidate-scoped — is a config/adapter change, not a rewrite.
- No persistence across backend restarts until that swap happens.

The promised interface is built in ADR 0021 (`SessionStore`,
`backend/app/session_store.py`); this ADR's decision to stay in-memory
for now is otherwise unchanged.
