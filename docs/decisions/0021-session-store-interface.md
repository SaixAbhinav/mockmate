# ADR 0021: Session store — the interface ADR 0007 promised

Date: 2026-07-21 · Status: accepted

## Context

ADR 0007 decided sessions would live in an in-memory dict "behind a small
interface, mirroring the `LLMProvider` pattern (`backend/app/providers.py`)"
so that swapping to a real database later would be "a config/adapter
change, not a rewrite." That interface was never built: `_sessions` and
`_evaluations` were read and written directly at call sites throughout
`main.py`. Until now, ADR 0007's stated consequence was false — a database
swap would have meant touching every one of those call sites.

## Decision

A `SessionStore` Protocol in `backend/app/session_store.py`, with one
implementation and a module-level factory — the exact shape of
`LLMProvider`/`get_provider()`:

- `SessionStore.get(session_id)`, `.save(state)`, `.get_evaluation(session_id)`,
  `.save_evaluation(session_id, evaluation)`.
- `InMemorySessionStore`: the same two plain dicts as before, now behind the
  interface, with identical behavior.
- `get_store()`: unlike `get_provider()`, which builds a fresh stateless
  wrapper on every call, `get_store()` returns the **same instance** every
  time — a module-level singleton. Sessions must survive across requests;
  a fresh store per call would silently forget every Session after the
  first request.

This covers exactly Sessions and Evaluations. Two adjacent dicts stay out:

- `_evaluation_locks` — an `asyncio.Lock` per Session is live in-process
  coordination, not state. It cannot be meaningfully persisted, so putting
  it behind a storage interface would make the interface dishonest.
- `_resumes` — keyed by `resume_id`, not `session_id`; a different
  lifecycle; holds PII. Out of scope for this refactor.

Every `SessionStore` method is `async def`, even though
`InMemorySessionStore` never awaits anything. Every call site is already
inside an `async def`, and the entire point of this interface is that a
future database-backed implementation — which *would* need to await — is a
drop-in replacement. A sync interface today would mean a second edit pass
at every call site later, exactly the cost this seam exists to avoid.

This ADR amends and fulfills ADR 0007 rather than replacing it: the
decision to keep state in-memory for now stands, only the promised
interface is now built.

## Consequences

- A real persistence backend (SQLite or otherwise) is a single new class
  implementing `SessionStore` plus a one-line edit to `get_store()` — no
  endpoint in `main.py` changes.
- Nothing changes yet in what the app does: state is still in-memory,
  still anonymous (ADR 0009), and still lost on a backend restart.
- `main.py` no longer reads or writes `_sessions`/`_evaluations` directly;
  every access goes through `get_store()`.
