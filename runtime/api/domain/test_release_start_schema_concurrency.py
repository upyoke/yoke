"""Release drivers started together converge one database one at a time.

On 2026-10-21 a stage and a production run started together on one control
plane both created the release's missing table, and the second crashed on
``pg_type_typname_nsp_index``. These tests run two converges against one
database at once, hold the lock to see the refusal name its holder, and feed
a concurrent-creation error to see it retried.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_helpers, release_start_schema_lock, schema_creation
from yoke_core.domain.release_start_schema import (
    CONCURRENT_CREATION_ATTEMPTS,
    CONVERGENCE_FAILED,
    LOCK_UNAVAILABLE,
    ReleaseStartSchemaError,
    converge_release_start_schema,
)
from yoke_core.domain.schema_common import _table_exists

_NEW_TABLE = "merge_queue_landing_attempts"


@pytest.fixture
def previous_release_db(monkeypatch):
    """A database missing one table, reached by an in-process driver."""
    from yoke_cli.transport import https as https_transport

    monkeypatch.setattr(
        https_transport, "resolve_https_connection", lambda *_a, **_k: None
    )
    with pg_testdb.test_database() as conn:
        conn.execute(f"DROP TABLE {_NEW_TABLE} CASCADE")
        conn.commit()
        yield conn


def test_two_drivers_converge_together_and_both_succeed(
    previous_release_db, monkeypatch
) -> None:
    real_converge = schema_creation.converge_additive_schema
    inside: list[str] = []
    overlaps: list[tuple[str, ...]] = []

    def observed_converge(conn) -> None:
        name = threading.current_thread().name
        inside.append(name)
        if len(inside) > 1:
            overlaps.append(tuple(inside))
        try:
            time.sleep(0.3)
            real_converge(conn)
        finally:
            inside.remove(name)

    monkeypatch.setattr(schema_creation, "converge_additive_schema", observed_converge)
    start = threading.Barrier(2)
    results: dict[str, object] = {}

    def drive(run_id: str) -> None:
        start.wait()
        try:
            results[run_id] = converge_release_start_schema(run_id)
        except Exception as exc:  # noqa: BLE001 - asserted below
            results[run_id] = exc

    drivers = [
        threading.Thread(target=drive, args=(run_id,), name=run_id)
        for run_id in ("run-stage", "run-production")
    ]
    for driver in drivers:
        driver.start()
    for driver in drivers:
        driver.join(timeout=60)

    assert results == {"run-stage": True, "run-production": True}
    assert overlaps == []
    assert _table_exists(previous_release_db, _NEW_TABLE)


def test_lock_held_past_the_wait_refuses_naming_the_holding_run(
    previous_release_db, monkeypatch
) -> None:
    monkeypatch.setattr(release_start_schema_lock, "LOCK_WAIT_SECONDS", 0.2)
    holder = db_helpers.connect()
    try:
        holder.execute(
            "SELECT set_config('application_name', %s, false)",
            ("yoke-release-start:run-holder",),
        )
        holder.execute(
            "SELECT pg_advisory_lock(%s)", (release_start_schema_lock.LOCK_KEY,)
        )
        holder.commit()
        with pytest.raises(ReleaseStartSchemaError) as refused:
            converge_release_start_schema("run-waiter")
    finally:
        holder.close()

    assert refused.value.code == LOCK_UNAVAILABLE
    assert "run run-holder" in str(refused.value)
    assert "yoke watch deploy -- run-waiter" in str(refused.value)
    assert not _table_exists(previous_release_db, _NEW_TABLE)


class _ConcurrentTypeCreation(psycopg.errors.UniqueViolation):
    diag = SimpleNamespace(constraint_name="pg_type_typname_nsp_index")


def test_a_concurrent_creation_is_retried(previous_release_db, monkeypatch) -> None:
    real_converge = schema_creation.converge_additive_schema
    calls: list[int] = []

    def raced_once(conn) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise _ConcurrentTypeCreation("duplicate key value")
        real_converge(conn)

    monkeypatch.setattr(schema_creation, "converge_additive_schema", raced_once)

    assert converge_release_start_schema("run-raced") is True
    assert len(calls) == 2
    assert _table_exists(previous_release_db, _NEW_TABLE)


def test_a_creation_race_that_persists_refuses_without_blaming_grants(
    previous_release_db, monkeypatch
) -> None:
    calls: list[int] = []

    def always_raced(_conn) -> None:
        calls.append(1)
        raise _ConcurrentTypeCreation("duplicate key value")

    monkeypatch.setattr(schema_creation, "converge_additive_schema", always_raced)

    with pytest.raises(ReleaseStartSchemaError) as refused:
        converge_release_start_schema("run-raced")

    assert len(calls) == CONCURRENT_CREATION_ATTEMPTS
    assert refused.value.code == CONVERGENCE_FAILED
    assert "role grant" not in str(refused.value)
    assert "yoke watch deploy -- run-raced" in str(refused.value)
