"""The release carrying a session's held item, and that member's own QA.

Two rules are pinned here because both were wrong in an earlier shape: the
newest run is not automatically the current delivery, and a member's QA state
is its own — two members of one run, held by one session, keep separate
answers.
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
            CREATE TABLE qa_requirements (
                id INTEGER PRIMARY KEY,
                deployment_run_id TEXT,
                deployment_member_item_id INTEGER,
                waived_at TEXT
            );
            CREATE TABLE qa_runs (
                id INTEGER PRIMARY KEY,
                qa_requirement_id INTEGER,
                verdict TEXT,
                case_outcome TEXT,
                execution_status TEXT
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
            "INSERT INTO items VALUES (?,1,?,'implementing','dash',1)",
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
) -> None:
    conn.execute(
        "INSERT INTO deployment_runs VALUES (?,?,?,?)", (run_id, status, stage, at)
    )
    for item_id in items:
        conn.execute("INSERT INTO deployment_run_items VALUES (?,?)", (run_id, item_id))


def _case(
    conn: sqlite3.Connection,
    requirement_id: int,
    run_id: str,
    item_id: int,
    *,
    verdict: str | None = None,
    case_outcome: str | None = None,
    execution_status: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO qa_requirements VALUES (?,?,?,NULL)",
        (requirement_id, run_id, item_id),
    )
    conn.execute(
        "INSERT INTO qa_runs VALUES (?,?,?,?,?)",
        (requirement_id, requirement_id, verdict, case_outcome, execution_status),
    )


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


def test_two_members_of_one_run_keep_their_own_qa_states() -> None:
    conn = _connection()
    _run(conn, "run-001", "executing", "item-qa", "2026-09-01T10:00:00Z", items=(7, 8))
    _case(conn, 1, "run-001", 7, verdict="fail")
    _case(conn, 2, "run-001", 8, verdict="pass")

    projected = primary_item_delivery_by_session(
        conn, [{"session_id": "s1"}, {"session_id": "s2"}]
    )
    assert projected["s1"]["item_qa"] == "failed"
    assert projected["s2"]["item_qa"] == "passed"
    # Both are riding the same release, which is the point of holding them apart.
    assert projected["s1"]["run_id"] == projected["s2"]["run_id"] == "run-001"


def test_a_member_with_several_cases_reports_the_one_needing_an_answer() -> None:
    # A later passing case must not hide an earlier failure.
    conn = _connection()
    _run(conn, "run-001", "executing", "item-qa", "2026-09-01T10:00:00Z")
    _case(conn, 1, "run-001", 7, verdict="fail")
    _case(conn, 2, "run-001", 7, verdict="pass")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["item_qa"] == "failed"


def test_a_member_with_no_recorded_case_reports_no_qa_state() -> None:
    conn = _connection()
    _run(conn, "run-001", "executing", "stage-deploy", "2026-09-01T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["item_qa"] is None


def test_an_item_no_release_carries_reports_nothing() -> None:
    assert primary_item_delivery_by_session(_connection(), [{"session_id": "s1"}]) == {}


def test_a_universe_without_deployment_tables_reports_nothing() -> None:
    # A minimal-schema fixture is a real shape the roster reads; answering
    # nothing there is different from answering a status it cannot know.
    conn = _connection(with_runs=False)

    assert primary_item_delivery_by_session(conn, [{"session_id": "s1"}]) == {}
