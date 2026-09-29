"""Live steering seats retain their document identity across boot convergence."""

from __future__ import annotations

import importlib
import sqlite3

import pytest

from yoke_core.domain.work_claim_targets import make_steering_target


migration = importlib.import_module(
    "yoke_core.domain.migrations.0048_pair_active_steering_document_locks"
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
            scope TEXT, released_at TEXT
        );
        CREATE TABLE strategy_doc_claims (
            id INTEGER PRIMARY KEY, owner_kind TEXT, owner_session_id TEXT,
            project_id INTEGER, strategy_doc_slug TEXT, released_at TEXT
        );
        """
    )
    for claim_id, document in ((1, None), (2, "RELEASES")):
        conn.execute(
            "INSERT INTO work_claims VALUES (?, 'holder', 'steering', ?, NULL)",
            (claim_id, make_steering_target(10, document).scope_json()),
        )
    for lock_id, slug in ((11, "CURRENT-PLAN"), (12, "RELEASES")):
        conn.execute(
            "INSERT INTO strategy_doc_claims VALUES "
            "(?, 'session', 'holder', 10, ?, NULL)",
            (lock_id, slug),
        )
    return conn


def test_existing_live_locks_pair_with_their_exact_seats_idempotently() -> None:
    conn = _connection()

    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)

    rows = conn.execute(
        "SELECT id, steering_claim_id FROM strategy_doc_claims ORDER BY id"
    ).fetchall()
    assert [(row["id"], row["steering_claim_id"]) for row in rows] == [
        (11, 1),
        (12, 2),
    ]


def test_ambiguous_project_lock_pairing_refuses() -> None:
    conn = _connection()
    conn.execute("DELETE FROM work_claims WHERE id = 2")

    with pytest.raises(AssertionError, match="ambiguous project-seat document locks"):
        migration.apply(conn)
