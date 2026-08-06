"""Migration harness completion and rollback events reach the ledger."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.migration_harness_contract import AuditEmissionError
from yoke_core.domain.migration_harness_events import _emit_event


def test_migration_event_persists_with_registered_source_type(tmp_path) -> None:
    db_path = str(tmp_path / "events.db")
    with sqlite3.connect(db_path) as conn:
        ensure_event_schema(conn)

    _emit_event(
        db_path,
        "MigrationCompleted",
        {"migration": "0001_example"},
        severity="INFO",
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT source_type, event_name FROM events"
        ).fetchone()
    assert row == ("script", "MigrationCompleted")


def test_migration_event_refusal_is_not_silently_discarded(
    monkeypatch, tmp_path,
) -> None:
    from yoke_core.domain import events

    monkeypatch.setattr(
        events,
        "emit_event",
        lambda *_args, **_kwargs: events.EmitResult(False, reason="exception"),
    )
    with pytest.raises(AuditEmissionError, match="could not persist"):
        _emit_event(str(tmp_path / "events.db"), "MigrationCompleted", {})
