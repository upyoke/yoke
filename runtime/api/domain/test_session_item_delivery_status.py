"""The release carrying a session's held item, and that member's own QA.

Pinned here because it was wrong in an earlier shape: the newest run is not
automatically the current delivery. The member's QA half is read from the
acceptance projection the release gate consults, so its own regressions live
beside that authority in ``test_session_item_release_qa``.
"""

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
            workflow_version_id INTEGER,
            deployment_flow TEXT
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
                created_at TEXT,
                flow TEXT
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
    for item_id, sequence, session_id, claim_id in (
        (7, 20, "s1", 1),
        (8, 21, "s2", 2),
    ):
        conn.execute(
            "INSERT INTO items VALUES (?,1,?,'implementing','dash',1,'prod-flow')",
            (item_id, sequence),
        )
        conn.execute(
            "INSERT INTO work_claims VALUES (?,?,'item',?,?,NULL)",
            (
                claim_id,
                session_id,
                make_item_target(item_id).scope_json(),
                "2026-09-01T12:00:00Z",
            ),
        )
    return conn


def _run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    stage: str,
    at: str,
    *,
    items: tuple[int, ...] = (7,),
    flow: str = "prod-flow",
) -> None:
    conn.execute(
        "INSERT INTO deployment_runs VALUES (?,?,?,?,?)",
        (run_id, status, stage, at, flow),
    )
    for item_id in items:
        conn.execute("INSERT INTO deployment_run_items VALUES (?,?)", (run_id, item_id))


def test_the_live_release_wins_over_a_newer_finished_one() -> None:
    # A cancelled release stays in an item's history. Reporting the newest row
    # would present an abandoned candidate as the one in flight.
    conn = _connection()
    _run(conn, "run-001", "executing", "item-qa", "2026-09-01T10:00:00Z")
    _run(conn, "run-002", "cancelled", "stage-deploy", "2026-09-02T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["run_id"] == "run-001"
    assert delivery["status"] == "executing"
    assert delivery["live"] is True


def test_every_release_finished_reports_the_newest_as_history() -> None:
    conn = _connection()
    _run(conn, "run-001", "succeeded", "complete", "2026-09-01T10:00:00Z")
    _run(conn, "run-002", "cancelled", "stage-deploy", "2026-09-02T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["run_id"] == "run-002"
    assert delivery["status"] == "cancelled"
    assert delivery["live"] is False


def test_statuses_are_carried_as_stored() -> None:
    conn = _connection()
    _run(conn, "run-001", "failed", "production", "2026-09-01T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["status"] == "failed"
    assert delivery["stage"] == "production"


def test_a_universe_with_no_scoped_qa_reports_no_item_qa() -> None:
    # Scoped QA standing is read from the acceptance projection, which has
    # nothing to answer for a run whose flow declares no QA stage. Absent is
    # absent: reporting "accepted" here would claim a release passed checks
    # it never carried.
    conn = _connection()
    _run(conn, "run-001", "executing", "stage-deploy", "2026-09-01T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["item_qa"] is None
    assert delivery["item_qa_reason"] is None


def test_a_newer_ancillary_run_does_not_become_the_release() -> None:
    conn = _connection()
    _run(conn, "run-prod", "executing", "item-qa", "2026-09-01T10:00:00Z")
    _run(
        conn, "run-stage", "succeeded", "complete", "2026-09-02T10:00:00Z",
        flow="stage-flow",
    )

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["run_id"] == "run-prod"
    assert delivery["live"] is True


def test_an_item_no_release_carries_reports_nothing() -> None:
    assert primary_item_delivery_by_session(_connection(), [{"session_id": "s1"}]) == {}


def test_a_universe_without_deployment_tables_reports_nothing() -> None:
    # A minimal-schema fixture is a real shape the roster reads; answering
    # nothing there is different from answering a status it cannot know.
    conn = _connection(with_runs=False)

    assert primary_item_delivery_by_session(conn, [{"session_id": "s1"}]) == {}
