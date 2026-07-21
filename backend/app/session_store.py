"""Session state behind one interface (ADR 0007, ADR 0021).

Mirrors `LLMProvider` (`backend/app/providers.py`): a `Protocol`, one
implementation, and a module-level factory. `main.py` only ever calls
`get_store()` — never a concrete class — so a database-backed store is a
drop-in replacement later, not a rewrite.

Covers exactly Sessions and Evaluations. `_evaluation_locks` (live
in-process coordination, not state) and `_resumes` (different lifecycle,
holds PII) stay out of this interface — see ADR 0021.
"""

from typing import Protocol

from .agent import InterviewState


class SessionStore(Protocol):
    async def get(self, session_id: str) -> InterviewState | None:
        """Look up a Session by id. `None` if it does not exist."""
        ...

    async def save(self, state: InterviewState) -> None:
        """Persist a Session, keyed by its own `session_id`."""
        ...

    async def get_evaluation(self, session_id: str) -> dict | None:
        """Look up a cached Evaluation by session id. `None` if not cached."""
        ...

    async def save_evaluation(self, session_id: str, evaluation: dict) -> None:
        """Cache a Session's Evaluation."""
        ...


class InMemorySessionStore:
    """Two plain dicts, exactly today's behavior (ADR 0007).

    Every method is `async def` even though nothing here awaits: every call
    site is already inside an `async def`, and the point of this interface is
    that a future database-backed store — which *would* need to await — is a
    drop-in replacement with no second edit pass at the call sites.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, InterviewState] = {}
        self._evaluations: dict[str, dict] = {}

    async def get(self, session_id: str) -> InterviewState | None:
        return self._sessions.get(session_id)

    async def save(self, state: InterviewState) -> None:
        self._sessions[state["session_id"]] = state

    async def get_evaluation(self, session_id: str) -> dict | None:
        return self._evaluations.get(session_id)

    async def save_evaluation(self, session_id: str, evaluation: dict) -> None:
        self._evaluations[session_id] = evaluation


# A single instance for the process's lifetime: state must persist across
# requests, unlike `get_provider()` (providers are stateless HTTP wrappers,
# so a fresh one per call is fine; a fresh store per call would silently
# forget every Session after the first request).
_store = InMemorySessionStore()


def get_store() -> SessionStore:
    return _store
