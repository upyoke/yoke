"""Snapshot notification display state onto addressed deliveries.

The event ledger is telemetry and may not be queried as application state.
Existing Inbox deliveries predate their owned display snapshot, so this
additive entry adds the columns when necessary and copies each source event's
current display fields once. Replays leave completed snapshots untouched.

No minimum serving version is needed: this entry removes no surface, and an
older build continues to join the event row exactly as it did before.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.inbox_notification_projection_contract import (
    DELIVERY_SNAPSHOT_COLUMNS,
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def apply(conn: Any) -> None:
    """Add and backfill the projection without committing the transaction."""
    from yoke_core.domain.schema_common import (
        _add_column_if_not_exists,
        _table_exists,
    )

    if not _table_exists(conn, "addressed_event_deliveries"):
        return
    for column, definition in DELIVERY_SNAPSHOT_COLUMNS:
        _add_column_if_not_exists(
            conn,
            "addressed_event_deliveries",
            column,
            definition,
        )

    # Existing events tables do not gain actor_id from ambient schema
    # converge; this history entry is the surface that needs the column
    # for the display-snapshot backfill, so it adds the column when absent.
    if _table_exists(conn, "events"):
        _add_column_if_not_exists(
            conn,
            "events",
            "actor_id",
            "INTEGER REFERENCES actors(id)",
        )

    rows = conn.execute(
        "SELECT d.id, e.event_name, e.project_id, e.event_outcome, e.actor_id, "
        "COALESCE(dl.label, a.system_component, "
        "'actor ' || CAST(e.actor_id AS TEXT)) AS event_actor_label, "
        "COALESCE(e.envelope, '{}') AS event_envelope "
        "FROM addressed_event_deliveries d "
        "LEFT JOIN events e ON e.event_id = d.event_id "
        "LEFT JOIN actors a ON a.id = e.actor_id "
        "LEFT JOIN actor_labels dl "
        "ON dl.actor_id = e.actor_id AND dl.surface = 'display' "
        "WHERE d.event_name IS NULL OR d.event_envelope IS NULL "
        "ORDER BY d.id"
    ).fetchall()
    marker = _marker(conn)
    for row in rows:
        conn.execute(
            "UPDATE addressed_event_deliveries SET "
            f"event_name={marker}, project_id={marker}, "
            f"event_outcome={marker}, event_actor_id={marker}, "
            f"event_actor_label={marker}, event_envelope={marker} "
            f"WHERE id={marker}",
            (row[1], row[2], row[3], row[4], row[5], row[6], row[0]),
        )


def invariants(conn: Any) -> None:
    """Prove every delivery carries a complete, valid display snapshot."""
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    if not _table_exists(conn, "addressed_event_deliveries"):
        return
    missing = [
        column
        for column, _definition in DELIVERY_SNAPSHOT_COLUMNS
        if not _column_exists(conn, "addressed_event_deliveries", column)
    ]
    if missing:
        raise AssertionError(
            "addressed delivery snapshot columns are missing: " + ", ".join(missing)
        )

    incomplete = conn.execute(
        "SELECT id FROM addressed_event_deliveries "
        "WHERE event_name IS NULL OR TRIM(event_name) = '' "
        "OR event_envelope IS NULL "
        "OR (event_actor_id IS NOT NULL AND "
        "event_actor_label IS NULL) "
        "ORDER BY id"
    ).fetchall()
    if incomplete:
        raise AssertionError(
            "addressed deliveries lack event snapshots: "
            + ", ".join(str(row[0]) for row in incomplete[:20])
        )

    invalid_json: list[str] = []
    for row in conn.execute(
        "SELECT id, event_envelope FROM addressed_event_deliveries ORDER BY id"
    ).fetchall():
        try:
            json.loads(str(row[1]))
        except (TypeError, json.JSONDecodeError):
            invalid_json.append(str(row[0]))
    if invalid_json:
        raise AssertionError(
            "addressed deliveries have invalid event envelopes: "
            + ", ".join(invalid_json[:20])
        )


__all__ = ["apply", "invariants"]
