"""Tests for `SessionStore` implementations (ADR 0021, ADR 0029).

Shared behavior is parametrized across BOTH `InMemorySessionStore` and
`DynamoDBSessionStore` so the two backends are proven identical - in
particular the `claim_evaluation` atomic-guard semantics that replace the
in-process `_evaluation_locks` (ADR 0029, "Race A": two Lambda containers
racing to compute the same Session's Evaluation).
"""

import asyncio
import os

import boto3
import pytest
from moto import mock_aws

from app.session_store import DynamoDBSessionStore, InMemorySessionStore

pytestmark = pytest.mark.anyio

TABLE_NAME = "mockmate-test"


def _make_in_memory_store() -> InMemorySessionStore:
    return InMemorySessionStore()


def _make_dynamodb_store() -> DynamoDBSessionStore:
    return DynamoDBSessionStore(table_name=TABLE_NAME, region_name="us-east-1")


@pytest.fixture
def in_memory_store():
    return _make_in_memory_store()


@pytest.fixture
def dynamodb_store():
    # moto intercepts every boto3 call made inside this context, including
    # the ones DynamoDBSessionStore makes lazily via asyncio.to_thread.
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()
        yield _make_dynamodb_store()


# Both fixtures are threaded through every shared test via this list of
# fixture names, so `pytest.mark.parametrize` + `request.getfixturevalue`
# gives one test body proving identical behavior on both backends.
BACKENDS = ["in_memory_store", "dynamodb_store"]


def _nontrivial_state(session_id: str) -> dict:
    # A stand-in for `InterviewState` (a TypedDict, so a plain dict satisfies
    # it at runtime) with nested structure, to prove the JSON round-trip
    # handles more than flat scalars.
    return {
        "session_id": session_id,
        "domain": "ml_genai",
        "queue": [{"id": "q1", "prompt": "Explain overfitting."}],
        "current_question": {"id": "q1", "prompt": "Explain overfitting."},
        "follow_up_count": 1,
        "current_answered": False,
        "current_answers": ["it's when..."],
        "completed": [],
        "transcript": [{"role": "interviewer", "text": "Let's begin."}],
        "phase": "warm_up",
        "latest_answer": "",
        "reply": "",
        "classification": "",
    }


@pytest.mark.parametrize("backend", BACKENDS)
async def test_save_then_get_round_trips_nested_state(backend, request):
    store = request.getfixturevalue(backend)
    state = _nontrivial_state("session-1")

    await store.save(state)
    result = await store.get("session-1")

    assert result == state


@pytest.mark.parametrize("backend", BACKENDS)
async def test_get_is_none_for_unknown_session(backend, request):
    store = request.getfixturevalue(backend)

    assert await store.get("does-not-exist") is None


@pytest.mark.parametrize("backend", BACKENDS)
async def test_get_evaluation_is_none_before_save(backend, request):
    store = request.getfixturevalue(backend)

    assert await store.get_evaluation("session-1") is None


@pytest.mark.parametrize("backend", BACKENDS)
async def test_get_evaluation_returns_value_after_save(backend, request):
    store = request.getfixturevalue(backend)
    evaluation = {"overall_score": 7, "summary": "solid warm-up"}

    await store.save_evaluation("session-1", evaluation)

    assert await store.get_evaluation("session-1") == evaluation


@pytest.mark.parametrize("backend", BACKENDS)
async def test_get_evaluation_is_none_while_only_a_claim_exists(backend, request):
    store = request.getfixturevalue(backend)

    claimed = await store.claim_evaluation("session-1")

    assert claimed is True
    # status is "computing", not "done" - get_evaluation must not surface it.
    assert await store.get_evaluation("session-1") is None


@pytest.mark.parametrize("backend", BACKENDS)
async def test_second_claim_fails_while_first_is_still_computing(backend, request):
    store = request.getfixturevalue(backend)

    first = await store.claim_evaluation("session-1")
    second = await store.claim_evaluation("session-1")

    assert first is True
    assert second is False


@pytest.mark.parametrize("backend", BACKENDS)
async def test_release_frees_a_claim_for_a_later_retry(backend, request):
    store = request.getfixturevalue(backend)

    await store.claim_evaluation("session-1")
    await store.release_evaluation_claim("session-1")

    assert await store.claim_evaluation("session-1") is True


@pytest.mark.parametrize("backend", BACKENDS)
async def test_release_is_a_noop_once_evaluation_is_saved(backend, request):
    store = request.getfixturevalue(backend)
    evaluation = {"overall_score": 9, "summary": "great"}

    await store.claim_evaluation("session-1")
    await store.save_evaluation("session-1", evaluation)
    await store.release_evaluation_claim("session-1")

    # The claim must still be considered taken - a later claim_evaluation
    # must NOT reopen a done Evaluation for recomputation.
    assert await store.claim_evaluation("session-1") is False
    assert await store.get_evaluation("session-1") == evaluation


@pytest.mark.parametrize("backend", BACKENDS)
async def test_race_a_exactly_one_concurrent_claim_wins(backend, request):
    """The headline reproduction for ADR 0029's "Race A": many callers race
    to claim the same Session's Evaluation concurrently (the scenario two
    Lambda containers handling retried requests would hit, now that there is
    no shared in-process `asyncio.Lock` across them). Exactly one of the
    concurrent `claim_evaluation` calls must return True.

    Caveat: moto is an in-process mock, not a true distributed-concurrency
    oracle. This test proves the conditional-write logic
    (`attribute_not_exists(pk)`) is wired correctly on both backends; real
    cross-container atomicity under concurrent writes is a guarantee
    DynamoDB itself provides, not something moto can certify.
    """
    store = request.getfixturevalue(backend)

    results = await asyncio.gather(
        *(store.claim_evaluation("session-1") for _ in range(25))
    )

    assert results.count(True) == 1
    assert results.count(False) == 24


async def test_dynamodb_store_env_defaults(monkeypatch):
    monkeypatch.delenv("MOCKMATE_DDB_TABLE", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)

    store = DynamoDBSessionStore()

    assert store._table_name == "mockmate"
    assert store._region_name == "us-east-1"


async def test_dynamodb_store_reads_env_overrides(monkeypatch):
    monkeypatch.setenv("MOCKMATE_DDB_TABLE", "custom-table")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    store = DynamoDBSessionStore()

    assert store._table_name == "custom-table"
    assert store._region_name == "eu-west-1"


async def test_get_store_defaults_to_in_memory(monkeypatch):
    monkeypatch.delenv("SESSION_STORE", raising=False)
    # Reimport-free: get_store() reads the env var fresh on module import in
    # the current implementation is not assumed here - only the documented
    # default-instance behavior is asserted via the public API.
    from app.session_store import get_store

    assert isinstance(get_store(), InMemorySessionStore)


async def test_get_store_is_a_singleton():
    from app.session_store import get_store

    assert get_store() is get_store()


@pytest.fixture
def clean_dynamodb_singleton():
    """Isolates the `SESSION_STORE=dynamodb` branch of `get_store()`.

    `_dynamodb_store` is a module-level singleton, same as `_store` - so a
    test that flips it on must reset it afterwards, or a later test in the
    same process (e.g. `test_get_store_defaults_to_in_memory`) could
    observe a leftover instance instead of exercising a fresh `get_store()`
    call. `_get_table()` is lazy (per the brief), so constructing the store
    here never touches AWS/moto - no table or region setup is needed.
    """
    import app.session_store as session_store_module

    yield session_store_module
    session_store_module._dynamodb_store = None


async def test_get_store_returns_dynamodb_store_when_env_selects_it(
    monkeypatch, clean_dynamodb_singleton
):
    monkeypatch.setenv("SESSION_STORE", "dynamodb")

    store = clean_dynamodb_singleton.get_store()

    assert isinstance(store, DynamoDBSessionStore)


async def test_get_store_dynamodb_path_is_also_a_singleton(
    monkeypatch, clean_dynamodb_singleton
):
    monkeypatch.setenv("SESSION_STORE", "dynamodb")

    assert clean_dynamodb_singleton.get_store() is clean_dynamodb_singleton.get_store()
