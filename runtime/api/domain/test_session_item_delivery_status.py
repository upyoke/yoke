"""The release carrying a session's held item, for the Sessions roster."""

from __future__ import annotations

import json
import sqlite3

from yoke_core.domain.session_item_delivery_status import (
    primary_item_delivery_by_session,
)
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def _connection(*, with_runs: bool = True) -> sqlite3.Connection:
    runtime = builtin_workflow_runtime("dash")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT,
            name TEXT,
            public_item_prefix TEXT
        );
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY,
            workflow_id TEXT,
            version INTEGER,
            definition_json TEXT,
            definition_digest TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            project_sequence INTEGER,
            status TEXT,
            workflow_id TEXT,
            workflow_version_id INTEGER
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        """
    )
    if with_runs:
        conn.executescript(
            """
            CREATE TABLE deployment_runs (
                id TEXT PRIMARY KEY,
                status TEXT,
                current_stage TEXT,
                created_at TEXT
            );
            CREATE TABLE deployment_run_items (
                run_id TEXT,
                item_id INTEGER
            );
            """
        )
    conn.execute("INSERT INTO projects VALUES (1,'yoke','Yoke','YOK')")
    conn.execute(
        "INSERT INTO workflow_versions VALUES (?,?,?,?,?)",
        (
            1,
            "dash",
            runtime.version,
            json.dumps(runtime.definition),
            runtime.definition_digest,
        ),
    )
    conn.execute("INSERT INTO items VALUES (7,1,20,'implementing','dash',1)")
    conn.execute(
        "INSERT INTO work_claims VALUES (1,'s1','item',?,?,NULL)",
        (make_item_target(7).scope_json(), "2026-09-01T12:00:00Z"),
    )
    return conn


def _run(conn: sqlite3.Connection, run_id: str, status: str, stage: str, at: str):
    conn.execute(
        "INSERT INTO deployment_runs VALUES (?,?,?,?)", (run_id, status, stage, at)
    )
    conn.execute("INSERT INTO deployment_run_items VALUES (?,7)", (run_id,))


def test_the_newest_release_carrying_the_item_is_the_one_reported() -> None:
    conn = _connection()
    _run(conn, "run-20260901-001", "succeeded", "complete", "2026-09-01T10:00:00Z")
    _run(conn, "run-20260902-001", "executing", "item-qa", "2026-09-02T10:00:00Z")

    assert primary_item_delivery_by_session(conn, [{"session_id": "s1"}]) == {
        "s1": {
            "run_id": "run-20260902-001",
            "status": "executing",
            "stage": "item-qa",
        }
    }


def test_an_item_no_release_carries_reports_nothing() -> None:
    conn = _connection()

    assert primary_item_delivery_by_session(conn, [{"session_id": "s1"}]) == {}


def test_a_universe_without_deployment_tables_reports_nothing() -> None:
    # A minimal-schema fixture is a real shape the roster reads; answering
    # nothing there is different from answering a status it cannot know.
    conn = _connection(with_runs=False)

    assert primary_item_delivery_by_session(conn, [{"session_id": "s1"}]) == {}


def test_a_session_holding_no_item_is_absent_from_the_projection() -> None:
    conn = _connection()
    _run(conn, "run-20260902-001", "executing", "item-qa", "2026-09-02T10:00:00Z")

    projected = primary_item_delivery_by_session(
        conn, [{"session_id": "s1"}, {"session_id": "s2"}]
    )
    assert set(projected) == {"s1"}
