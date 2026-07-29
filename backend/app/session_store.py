"""Session state behind one interface (ADR 0007, ADR 0021, ADR 0029).

Mirrors `LLMProvider` (`backend/app/providers.py`): a `Protocol`, its
implementations, and a module-level factory. `main.py` only ever calls
`get_store()` — never a concrete class — so a database-backed store is a
drop-in replacement, not a rewrite.

Covers exactly Sessions and Evaluations, plus (ADR 0029) the atomic
claim/release pair that decides who gets to compute a Session's Evaluation.
`_resumes` (different lifecycle, holds PII) stays out of this interface —
see ADR 0021.

ADR 0029 moves the app to serverless AWS, where a single in-process
`asyncio.Lock` (`_evaluation_locks` in `main.py`) no longer coordinates
callers across Lambda containers — two containers can each believe they are
the first to compute a given Session's Evaluation ("Race A"). `claim_evaluation`
/ `release_evaluation_claim` are the storage-backed replacement: whichever
backend is active, exactly one caller's claim succeeds. `main.py` still uses
`_evaluation_locks` today — rewiring the endpoint to these methods instead is
a separate follow-up PR; this one only adds the primitive and proves it on
both backends.
"""

import asyncio
import json
import os
from typing import Protocol

import boto3

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

    async def claim_evaluation(self, session_id: str) -> bool:
        """Atomically claim the sole right to compute this Session's Evaluation.

        Returns True to exactly one caller when no claim/Evaluation yet exists
        for session_id; returns False to every other caller. This is the
        idempotency guard that replaces the in-process `_evaluation_locks`
        (ADR 0029, Race A)."""
        ...

    async def release_evaluation_claim(self, session_id: str) -> None:
        """Release a claim that did not produce a saved Evaluation (e.g. a
        retryable provider failure), so a later caller can claim and retry.
        Must be a no-op if the Evaluation has already been saved (status done)."""
        ...


class InMemorySessionStore:
    """Two plain dicts, exactly today's behavior (ADR 0007), plus an
    in-memory claim marker (ADR 0029).

    Every method is `async def` even though nothing here awaits: every call
    site is already inside an `async def`, and the point of this interface is
    that a future database-backed store — which *would* need to await — is a
    drop-in replacement with no second edit pass at the call sites.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, InterviewState] = {}
        self._evaluations: dict[str, dict] = {}
        # "computing" (claimed, not yet saved) or "done" (mirrors _evaluations).
        self._eval_status: dict[str, str] = {}

    async def get(self, session_id: str) -> InterviewState | None:
        return self._sessions.get(session_id)

    async def save(self, state: InterviewState) -> None:
        self._sessions[state["session_id"]] = state

    async def get_evaluation(self, session_id: str) -> dict | None:
        return self._evaluations.get(session_id)

    async def save_evaluation(self, session_id: str, evaluation: dict) -> None:
        self._evaluations[session_id] = evaluation
        self._eval_status[session_id] = "done"

    async def claim_evaluation(self, session_id: str) -> bool:
        # No `await` between the check and the set, so this is atomic on the
        # event loop - the same reasoning `main.py` used to justify
        # `_evaluation_locks.setdefault` (ADR 0029, Race A).
        if session_id in self._eval_status or session_id in self._evaluations:
            return False
        self._eval_status[session_id] = "computing"
        return True

    async def release_evaluation_claim(self, session_id: str) -> None:
        if session_id in self._evaluations:
            return  # already done - release is a no-op.
        self._eval_status.pop(session_id, None)


class DynamoDBSessionStore:
    """Single-table DynamoDB store (ADR 0029): Sessions and Evaluations for
    one Session share a partition key (`pk` = session_id), distinguished by
    sort key (`sk` = "session" | "eval").

    State/Evaluation are stored as an opaque JSON blob in a `data`
    attribute rather than native DynamoDB attributes - this sidesteps
    DynamoDB's float-to-Decimal conversion and nested-type quirks entirely.
    `InterviewState` (a TypedDict, `agent.py`) is JSON-serializable.

    boto3 is synchronous; every call crosses to a thread via
    `asyncio.to_thread`, exactly as `runner.py` wraps its subprocess call.
    Do NOT add aioboto3 - this mirrors the rest of the codebase's approach
    to sync-library boundaries.
    """

    def __init__(self, table_name: str | None = None, region_name: str | None = None) -> None:
        self._table_name = table_name or os.getenv("MOCKMATE_DDB_TABLE", "mockmate")
        self._region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self._table = None  # built lazily - see _get_table.

    def _get_table(self):
        # Built lazily rather than in __init__: constructing a boto3
        # resource this early would bind moto's mock (in tests) or real
        # AWS credentials (in prod) at import time, before either is ready.
        if self._table is None:
            resource = boto3.resource("dynamodb", region_name=self._region_name)
            self._table = resource.Table(self._table_name)
        return self._table

    async def get(self, session_id: str) -> InterviewState | None:
        def _get():
            table = self._get_table()
            response = table.get_item(Key={"pk": session_id, "sk": "session"})
            item = response.get("Item")
            return json.loads(item["data"]) if item else None

        return await asyncio.to_thread(_get)

    async def save(self, state: InterviewState) -> None:
        def _save():
            table = self._get_table()
            table.put_item(
                Item={
                    "pk": state["session_id"],
                    "sk": "session",
                    "data": json.dumps(state),
                }
            )

        await asyncio.to_thread(_save)

    async def get_evaluation(self, session_id: str) -> dict | None:
        def _get():
            table = self._get_table()
            response = table.get_item(Key={"pk": session_id, "sk": "eval"})
            item = response.get("Item")
            if item is None or item.get("status") != "done":
                return None
            return json.loads(item["data"])

        return await asyncio.to_thread(_get)

    async def save_evaluation(self, session_id: str, evaluation: dict) -> None:
        def _save():
            table = self._get_table()
            # Overwrites any "computing" claim marker - saving finalizes.
            table.put_item(
                Item={
                    "pk": session_id,
                    "sk": "eval",
                    "status": "done",
                    "data": json.dumps(evaluation),
                }
            )

        await asyncio.to_thread(_save)

    async def claim_evaluation(self, session_id: str) -> bool:
        def _claim():
            table = self._get_table()
            try:
                table.put_item(
                    Item={"pk": session_id, "sk": "eval", "status": "computing"},
                    ConditionExpression="attribute_not_exists(pk)",
                )
                return True
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                return False

        return await asyncio.to_thread(_claim)

    async def release_evaluation_claim(self, session_id: str) -> None:
        def _release():
            table = self._get_table()
            try:
                table.delete_item(
                    Key={"pk": session_id, "sk": "eval"},
                    ConditionExpression="attribute_exists(pk) AND #s <> :done",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":done": "done"},
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass  # already done, or already absent - a no-op either way.

        await asyncio.to_thread(_release)


# A single instance for the process's lifetime: state must persist across
# requests, unlike `get_provider()` (providers are stateless HTTP wrappers,
# so a fresh one per call is fine; a fresh store per call would silently
# forget every Session after the first request).
_store = InMemorySessionStore()
_dynamodb_store: DynamoDBSessionStore | None = None


def get_store() -> SessionStore:
    if os.getenv("SESSION_STORE") == "dynamodb":
        global _dynamodb_store
        if _dynamodb_store is None:
            _dynamodb_store = DynamoDBSessionStore()
        return _dynamodb_store
    return _store
