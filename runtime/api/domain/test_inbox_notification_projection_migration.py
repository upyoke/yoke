"""Coverage for the addressed-notification snapshot history entry."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.decision_request_events import append_decision_event_envelope
from yoke_core.domain.inbox_notification_projection_contract import (
    DELIVERY_SNAPSHOT_COLUMNS,
)
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)


_ENTRY_SLUG = "inbox_notification_projection"
_entry = next(
    entry
    for entry in ordered_entries(history_dir(migration_history_package))
    if entry.name.endswith(_ENTRY_SLUG)
)
migration = load_migration_module(_entry.path, _entry.name)


def _legacy_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE actors (id INTEGER PRIMARY KEY, kind TEXT, system_component TEXT)"
    )
    conn.execute(
        "CREATE TABLE actor_labels ("
        "id INTEGER PRIMARY KEY, actor_id INTEGER, surface TEXT, label TEXT)"
    )
    conn.execute(
        "CREATE TABLE events ("
        "event_id TEXT PRIMARY KEY, event_name TEXT NOT NULL, "
        "project_id INTEGER, event_outcome TEXT, actor_id INTEGER, envelope TEXT)"
    )
    conn.execute(
        "CREATE TABLE addressed_event_deliveries ("
        "id INTEGER PRIMARY KEY, channel TEXT NOT NULL, event_id TEXT NOT NULL, "
        "actor_id INTEGER NOT NULL, notification_kind TEXT NOT NULL, "
        "reason TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO actors VALUES (?, ?, ?)",
        (
            (1, "human", None),
            (2, "human", None),
            (3, "system", "release-runner"),
            (4, "human", None),
        ),
    )
    conn.execute("INSERT INTO actor_labels VALUES (1, 2, 'display', 'Release owner')")
    events = (
        (
            "event-display",
            "DecisionRequestResolved",
            10,
            "completed",
            2,
            json.dumps(
                {
                    "event_id": "event-display",
                    "event_name": "DecisionRequestResolved",
                    "context": {"request_id": 7},
                }
            ),
        ),
        (
            "event-system",
            "DeploymentRunFailed",
            None,
            "failed",
            3,
            json.dumps(
                {
                    "event_id": "event-system",
                    "event_name": "DeploymentRunFailed",
                    "context": {"run_id": "run-7"},
                }
            ),
        ),
        ("event-fallback", "ItemBlocked", 10, None, 4, None),
        ("event-anonymous", "ItemUnblocked", 10, "completed", None, "{}"),
    )
    conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", events)
    deliveries = tuple(
        (
            index,
            "in_app",
            event[0],
            1,
            "decision_request_resolved",
            "snapshot proof",
            None,
            f"2026-08-05T12:0{index}:00Z",
        )
        for index, event in enumerate(events, 1)
    )
    conn.executemany(
        "INSERT INTO addressed_event_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        deliveries,
    )
    return conn


def _snapshots(conn) -> list[tuple[object, ...]]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT event_name, project_id, event_outcome, event_actor_id, "
            "event_actor_label, event_envelope "
            "FROM addressed_event_deliveries ORDER BY id"
        ).fetchall()
    ]


def test_sqlite_apply_backfills_display_inputs_and_is_idempotent() -> None:
    conn = _legacy_connection()

    migration.apply(conn)
    migration.invariants(conn)

    snapshots = _snapshots(conn)
    assert snapshots[0][:5] == (
        "DecisionRequestResolved",
        10,
        "completed",
        2,
        "Release owner",
    )
    assert snapshots[1][:5] == (
        "DeploymentRunFailed",
        None,
        "failed",
        3,
        "release-runner",
    )
    assert snapshots[2][:5] == ("ItemBlocked", 10, None, 4, "actor 4")
    assert json.loads(str(snapshots[2][5])) == {}
    assert snapshots[3][3:5] == (None, None)

    before = _snapshots(conn)
    conn.execute("UPDATE actor_labels SET label='Changed later' WHERE actor_id=2")
    conn.execute(
        "UPDATE events SET event_outcome='changed' WHERE event_id='event-display'"
    )
    migration.apply(conn)
    migration.invariants(conn)
    assert _snapshots(conn) == before


def test_invariants_reject_a_delivery_without_a_source_snapshot() -> None:
    conn = _legacy_connection()
    conn.execute(
        "INSERT INTO addressed_event_deliveries VALUES "
        "(99, 'in_app', 'missing-event', 1, 'decision_request_resolved', "
        "'orphan', NULL, 'now')"
    )

    migration.apply(conn)

    with pytest.raises(AssertionError, match="lack event snapshots: 99"):
        migration.invariants(conn)


def test_entry_is_additive_and_declares_no_serving_floor() -> None:
    assert getattr(migration, "MINIMUM_SERVING_VERSION", None) is None


def test_postgres_apply_adds_missing_events_actor_id(test_db) -> None:
    """Legacy events tables without actor_id still accept the backfill."""
    from yoke_core.domain.schema_common import _column_exists

    test_db.execute('ALTER TABLE events DROP COLUMN IF EXISTS "actor_id"')
    assert not _column_exists(test_db, "events", "actor_id")
    for column, _definition in reversed(DELIVERY_SNAPSHOT_COLUMNS):
        test_db.execute(
            f'ALTER TABLE addressed_event_deliveries DROP COLUMN "{column}"'
        )
    actor_id = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO events ("
        "event_id, source_type, session_id, severity, event_kind, event_type, "
        "event_name, event_outcome, project_id, envelope, created_at"
        ") VALUES ("
        "'legacy-no-actor', 'system', 'migration-proof', 'INFO', 'lifecycle', "
        "'state', 'ItemBlocked', 'completed', 1, '{}', '2026-08-05T12:00:00Z')"
    )
    test_db.execute(
        "INSERT INTO addressed_event_deliveries "
        "(channel, event_id, actor_id, notification_kind, reason, created_at) "
        "VALUES ('in_app', 'legacy-no-actor', %s, 'decision_request_resolved', "
        "'missing actor column', '2026-08-05T12:00:00Z')",
        (actor_id,),
    )

    migration.apply(test_db)
    migration.invariants(test_db)

    assert _column_exists(test_db, "events", "actor_id")
    row = test_db.execute(
        "SELECT event_name, event_actor_id, event_envelope "
        "FROM addressed_event_deliveries WHERE event_id=%s",
        ("legacy-no-actor",),
    ).fetchone()
    assert tuple(row) == ("ItemBlocked", None, "{}")


def test_postgres_apply_backfills_current_schema(test_db) -> None:
    for column, _definition in reversed(DELIVERY_SNAPSHOT_COLUMNS):
        test_db.execute(
            f'ALTER TABLE addressed_event_deliveries DROP COLUMN "{column}"'
        )
    actor_id = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    envelope = append_decision_event_envelope(
        test_db,
        "DecisionRequestResolved",
        actor_id=actor_id,
        session_id="migration-proof",
        project_id=1,
        org_id=None,
        context={"request_id": 7001},
        created_at="2026-08-05T12:00:00Z",
    )
    test_db.execute(
        "INSERT INTO addressed_event_deliveries "
        "(channel, event_id, actor_id, notification_kind, reason, created_at) "
        "VALUES ('in_app', %s, %s, 'decision_request_resolved', "
        "'migration proof', '2026-08-05T12:00:00Z')",
        (envelope["event_id"], actor_id),
    )

    migration.apply(test_db)
    migration.invariants(test_db)
    first = test_db.execute(
        "SELECT event_name, project_id, event_outcome, event_actor_id, "
        "event_actor_label, event_envelope FROM addressed_event_deliveries "
        "WHERE event_id=%s",
        (envelope["event_id"],),
    ).fetchone()
    migration.apply(test_db)
    migration.invariants(test_db)
    second = test_db.execute(
        "SELECT event_name, project_id, event_outcome, event_actor_id, "
        "event_actor_label, event_envelope FROM addressed_event_deliveries "
        "WHERE event_id=%s",
        (envelope["event_id"],),
    ).fetchone()

    assert tuple(first) == tuple(second)
    assert first[0:4] == ("DecisionRequestResolved", 1, "completed", actor_id)
    assert json.loads(str(first[5]))["context"] == {"request_id": 7001}
