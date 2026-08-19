"""Numeric item-dependency id cutover: resolve, drop orphans, replay."""

from __future__ import annotations

import importlib
import io
import sqlite3
from contextlib import redirect_stderr

from yoke_core.domain.migrations._numeric_item_dependency_ids import (
    rebuild_registry,
    registry_is_numeric,
)


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0012_numeric_item_dependency_ids"
)


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL,
            public_item_prefix TEXT NOT NULL
        );
        INSERT INTO projects VALUES (1, 'yoke', 'YOK');
        INSERT INTO projects VALUES (2, 'externalwebapp', 'EXT');
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            project_sequence INTEGER NOT NULL
        );
        INSERT INTO items VALUES (900, 1, 880);
        INSERT INTO items VALUES (901, 1, 881);
        INSERT INTO items VALUES (902, 2, 12);
        CREATE TABLE item_dependencies (
            id INTEGER PRIMARY KEY,
            dependent_item TEXT NOT NULL,
            blocking_item TEXT NOT NULL,
            gate_point TEXT NOT NULL DEFAULT 'activation',
            satisfaction TEXT NOT NULL DEFAULT 'status:done',
            source TEXT NOT NULL,
            session_id INTEGER,
            rationale TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        INSERT INTO item_dependencies VALUES
            (1, 'YOK-880', 'YOK-881', 'activation', 'status:done',
             'operator', NULL, 'public-ref pair', '{}', '2026-01-01T00:00:00Z');
        INSERT INTO item_dependencies VALUES
            (2, 'YOK-880', 'EXT-12', 'activation', 'status:done',
             'operator', NULL, 'cross-project', '{}', '2026-01-01T00:00:00Z');
        INSERT INTO item_dependencies VALUES
            (3, '901', '900', 'integration', 'fact:merged',
             'operator', NULL, 'numeric-tail pair', '{}', '2026-01-01T00:00:00Z');
        INSERT INTO item_dependencies VALUES
            (4, 'YOK-99999', 'YOK-881', 'activation', 'status:done',
             'operator', NULL, 'orphan dependent', '{}', '2026-01-01T00:00:00Z');
        INSERT INTO item_dependencies VALUES
            (5, 'YOK-880', 'GONE', 'activation', 'status:done',
             'operator', NULL, 'orphan blocker', '{}', '2026-01-01T00:00:00Z');
        """
    )
    return conn


def _stored(conn: sqlite3.Connection) -> list[tuple[int, int, int, str]]:
    return [
        (int(row["id"]), int(row["dependent_item_id"]),
         int(row["blocking_item_id"]), str(row["gate_point"]))
        for row in conn.execute(
            "SELECT id, dependent_item_id, blocking_item_id, gate_point "
            "FROM item_dependencies ORDER BY id"
        )
    ]


def test_migration_resolves_refs_and_drops_orphans() -> None:
    conn = _database()
    captured = io.StringIO()
    with redirect_stderr(captured):
        MIGRATION.apply(conn)
        MIGRATION.invariants(conn)

    report = captured.getvalue()
    assert "dropped orphan item_dependencies id=4" in report
    assert "dependent_item='YOK-99999'" in report
    assert "dropped orphan item_dependencies id=5" in report
    assert "blocking_item='GONE'" in report
    assert "dropped 2 orphan item_dependencies row(s)" in report
    assert _stored(conn) == [
        (1, 900, 901, "activation"),
        (2, 900, 902, "activation"),
        (3, 901, 900, "integration"),
    ]
    assert not any(
        name in {row[1] for row in conn.execute("PRAGMA table_info(item_dependencies)")}
        for name in ("dependent_item", "blocking_item")
    )


def test_migration_replay_is_a_no_op() -> None:
    conn = _database()
    MIGRATION.apply(conn)
    before = _stored(conn)
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    assert _stored(conn) == before


def test_already_numeric_registry_is_a_no_op() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE items (id INTEGER PRIMARY KEY);
        INSERT INTO items VALUES (1), (2);
        CREATE TABLE item_dependencies (
            id INTEGER PRIMARY KEY,
            dependent_item_id INTEGER NOT NULL REFERENCES items(id),
            blocking_item_id INTEGER NOT NULL REFERENCES items(id),
            gate_point TEXT NOT NULL DEFAULT 'activation',
            satisfaction TEXT NOT NULL DEFAULT 'status:done',
            source TEXT NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        INSERT INTO item_dependencies VALUES
            (1, 1, 2, 'activation', 'status:done', 'operator', '', '{}',
             '2026-01-01T00:00:00Z');
        """
    )
    assert registry_is_numeric(conn)
    rebuild_registry(conn)
    assert _stored(conn) == [(1, 1, 2, "activation")]


def test_migration_declares_a_serving_floor() -> None:
    assert MIGRATION.MINIMUM_SERVING_VERSION == "0.1.1+launch.239"
