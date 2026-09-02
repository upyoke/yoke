"""The entry that leaves the Inbox carrying gates and messages only.

Dropping a table and a column is destructive, so the entry carries a serving
floor. Its harder obligation is the closed ``kind`` vocabulary: the values it
writes into the narrowed CHECK have to be the four that survive THIS
retirement, whatever the build running the entry happens to believe today.
"""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.decision_request_contract import DECISION_REQUEST_KINDS
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    NEXT_RELEASE,
    declared_minimum,
    removes_a_surface,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists

ENTRY_NAME = "0033_drop_inbox_notification_substrate"


def _entry():
    """Load the entry the way the applier does: by path, not by import name."""
    directory = history_dir(migration_history_package)
    match = next(
        record for record in ordered_entries(directory)
        if record.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{match.name}.py", match.name)


entry = _entry()


def _substrate_shape() -> sqlite3.Connection:
    """A database still carrying the notification substrate."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE decision_requests (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            blocking INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE decision_request_role_authorities (
            request_id INTEGER NOT NULL,
            role_name TEXT NOT NULL
        );
        CREATE TABLE decision_request_actor_authorities (
            request_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL
        );
        CREATE TABLE addressed_event_deliveries (
            id INTEGER PRIMARY KEY,
            actor_id INTEGER NOT NULL,
            notification_kind TEXT NOT NULL,
            read_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_addressed_events_actor_unread
            ON addressed_event_deliveries(actor_id, read_at, created_at);
        CREATE TABLE event_registry (
            event_name TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'active'
        );
        """
    )
    conn.execute(
        "INSERT INTO decision_requests (id, kind, subject_key, blocking) "
        "VALUES (1, 'strategy_revision_review', '10:PLAN:7', 0)"
    )
    conn.execute(
        "INSERT INTO decision_requests (id, kind, subject_key, blocking) "
        "VALUES (2, 'qa_needs_review', '44', 1)"
    )
    conn.execute(
        "INSERT INTO decision_request_role_authorities VALUES (1, 'owner')"
    )
    conn.execute("INSERT INTO decision_request_actor_authorities VALUES (1, 3)")
    conn.execute(
        "INSERT INTO addressed_event_deliveries "
        "(id, actor_id, notification_kind, created_at) "
        "VALUES (1, 3, 'deployment_run_completed', '2026-09-02T00:00:00Z')"
    )
    for name in (*entry.RETIRED_EVENT_NAMES, "DecisionRequestResolved"):
        conn.execute("INSERT INTO event_registry (event_name) VALUES (?)", (name,))
    conn.commit()
    return conn


def test_the_delivery_substrate_and_the_blocking_flag_are_gone():
    conn = _substrate_shape()

    entry.apply(conn)

    assert not _table_exists(conn, entry.DELIVERY_TABLE)
    assert not _column_exists(conn, entry.REQUEST_TABLE, entry.RETIRED_COLUMN)


def test_the_retired_kind_leaves_no_row_and_no_orphan_authority():
    conn = _substrate_shape()

    entry.apply(conn)

    assert [row[0] for row in conn.execute(
        "SELECT kind FROM decision_requests ORDER BY id"
    )] == ["qa_needs_review"]
    for table in (
        "decision_request_role_authorities",
        "decision_request_actor_authorities",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_only_the_events_that_fed_the_deliveries_are_retired():
    conn = _substrate_shape()

    entry.apply(conn)

    assert [row[0] for row in conn.execute(
        "SELECT event_name FROM event_registry ORDER BY event_name"
    )] == ["DecisionRequestResolved"]


def test_applying_twice_converges_to_the_same_shape():
    """A database that already has the entry must not fail the second pass."""
    conn = _substrate_shape()

    entry.apply(conn)
    entry.apply(conn)

    entry.invariants(conn)


def test_the_narrowed_vocabulary_is_this_entry_s_own():
    """The CHECK values must not track whatever build applies the entry.

    Reading the live tuple would let a later release that adds a kind reach
    backwards and widen the constraint this entry exists to narrow, and would
    let a build that still carries the retired kind re-admit it.
    """
    assert entry.RETIRED_KIND not in entry.SURVIVING_KINDS
    assert set(entry.SURVIVING_KINDS) <= set(DECISION_REQUEST_KINDS)


def test_removing_a_surface_declares_a_serving_floor():
    directory = history_dir(migration_history_package)
    source = (directory / f"{ENTRY_NAME}.py").read_text()

    assert removes_a_surface(source)
    assert declared_minimum(entry) == NEXT_RELEASE
