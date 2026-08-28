"""The batched hook-telemetry flush must COMMIT the rows it writes.

This suite lives under ``runtime/api`` rather than beside the other hook
telemetry tests on purpose. ``runtime/harness/conftest.py`` carries an
autouse fixture that pins the flush to its no-shared-connection path so
per-module emission stays deterministic in bare unit runs — which also means
no test over there can ever exercise the shared connection the flush actually
uses in production. That blind spot is how a commit-less shared connection
silently discarded every ``HookDispatchTelemetry`` row for a month while the
emitters, the severity floor, and the event registry all stayed healthy.

The assertions here therefore read back through a SEPARATE connection: only a
second connection can distinguish a row that was committed from one that was
inserted into a transaction and rolled back at close.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.events_crud_test_fixtures import _apply_events_schema
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import events_writes
from yoke_core.hooks import telemetry


@pytest.fixture
def events_universe(tmp_path):
    """A disposable database carrying the schema the emitter actually targets."""
    with init_test_db(tmp_path, apply_schema=_apply_events_schema) as path:
        yield path


def _dispatch_record(session_id: str) -> tuple[str, dict]:
    return (
        "dispatch",
        {
            "hook_event": "PreToolUse",
            "executor": "claude",
            "chain_length": 2,
            "decision_outcome": "allow",
            "session_id": session_id,
            "item_id": None,
            "tool_name": "Bash",
            "duration_ms": 7,
            "extra": {"driver_pid": 4242, "driver_ppid": 4241},
        },
    )


def _stored_event(db_path: str, session_id: str):
    conn = connect_test_db(db_path)
    try:
        return conn.execute(
            "SELECT event_name, envelope FROM events "
            "WHERE session_id = %s AND event_name = %s",
            (session_id, "HookDispatchTelemetry"),
        ).fetchone()
    finally:
        conn.close()


def test_shared_connection_is_actually_opened(events_universe: str) -> None:
    """Guard the guard: a None connection would make the rest vacuous."""
    with events_writes.hook_emit_connection() as conn:
        assert conn is not None, (
            "this suite must exercise the SHARED-connection path; a None "
            "connection silently degrades to per-call connections that commit "
            "on their own, so the persistence assertions below would pass "
            "whether or not the flush commits"
        )


def test_batched_flush_persists_the_dispatch_row(events_universe: str) -> None:
    """A committed row: readable from a connection the flush never touched."""
    telemetry.flush_hook_telemetry([_dispatch_record("sess-flush-persist")])

    row = _stored_event(events_universe, "sess-flush-persist")
    assert row is not None, (
        "HookDispatchTelemetry did not survive the batched flush — the shared "
        "connection was closed without committing, so Postgres rolled the "
        "whole batch back"
    )
    context = json.loads(row["envelope"])["context"]
    assert context["driver_pid"] == 4242
    assert context["driver_ppid"] == 4241


def test_flush_commits_even_when_a_later_row_fails(events_universe: str) -> None:
    """One malformed row must not take the committed batch down with it."""
    good = _dispatch_record("sess-flush-partial")
    bad = ("dispatch", {"hook_event": "PreToolUse"})  # missing required kwargs

    telemetry.flush_hook_telemetry([good, bad])

    assert _stored_event(events_universe, "sess-flush-partial") is not None


@pytest.mark.parametrize("records", [[], None])
def test_empty_flush_is_a_noop(records, events_universe: str) -> None:
    """No records and no ensure-register means no connection work at all."""
    telemetry.flush_hook_telemetry(records or [])
