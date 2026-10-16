"""The release carrying a session's held item, and that member's own QA.

Pinned here because it was wrong in an earlier shape: the newest run is not
automatically the current delivery. The member's QA half is read from the
acceptance projection the release gate consults, so its own regressions live
beside that authority in ``test_session_item_release_qa``.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.session_item_delivery_status import primary_item_delivery_by_session


def _connection(conn: Any) -> Any:
    for flow in ("prod-flow", "stage-flow"):
        cmd_create(
            conn, flow, "yoke", flow, "",
            '[{"name":"deploy","stage_kind":"execution","step_runner":"auto"}]',
            status="active",
        )
    for item_id, sequence, session_id in ((7, 20, "s1"), (8, 21, "s2")):
        insert_item(
            conn, id=item_id, project_sequence=sequence, workflow_id="dash",
            status="implementing", deployment_flow="prod-flow",
        )
        insert_session(conn, session_id)
        insert_item_claim(conn, session_id, item_id)
    return conn


def _run(
    conn: Any,
    run_id: str,
    status: str,
    stage: str,
    at: str,
    *,
    items: tuple[int, ...] = (7,),
    flow: str = "prod-flow",
) -> None:
    insert_deployment_run(
        conn, id=run_id, status=status, current_stage=stage, created_at=at, flow=flow,
    )
    for item_id in items:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s,%s,%s)", (run_id, item_id, at),
        )
    conn.commit()


def test_the_live_release_wins_over_a_newer_finished_one(test_db) -> None:
    # A cancelled release stays in an item's history. Reporting the newest row
    # would present an abandoned candidate as the one in flight.
    conn = _connection(test_db)
    _run(conn, "run-001", "executing", "item-qa", "2026-09-01T10:00:00Z")
    _run(conn, "run-002", "cancelled", "stage-deploy", "2026-09-02T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["run_id"] == "run-001"
    assert delivery["status"] == "executing"
    assert delivery["live"] is True


def test_every_release_finished_reports_the_newest_as_history(test_db) -> None:
    conn = _connection(test_db)
    _run(conn, "run-001", "succeeded", "complete", "2026-09-01T10:00:00Z")
    _run(conn, "run-002", "cancelled", "stage-deploy", "2026-09-02T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["run_id"] == "run-002"
    assert delivery["status"] == "cancelled"
    assert delivery["live"] is False


def test_statuses_are_carried_as_stored(test_db) -> None:
    conn = _connection(test_db)
    _run(conn, "run-001", "failed", "production", "2026-09-01T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["status"] == "failed"
    assert delivery["stage"] == "production"


def test_a_universe_with_no_scoped_qa_reports_no_item_qa(test_db) -> None:
    # Scoped QA standing is read from the acceptance projection, which has
    # nothing to answer for a run whose flow declares no QA stage. Absent is
    # absent: reporting "accepted" here would claim a release passed checks
    # it never carried.
    conn = _connection(test_db)
    _run(conn, "run-001", "executing", "stage-deploy", "2026-09-01T10:00:00Z")

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["item_qa"] is None
    assert delivery["item_qa_reason"] is None


def test_a_newer_ancillary_run_does_not_become_the_release(test_db) -> None:
    conn = _connection(test_db)
    _run(conn, "run-prod", "executing", "item-qa", "2026-09-01T10:00:00Z")
    _run(
        conn, "run-stage", "succeeded", "complete", "2026-09-02T10:00:00Z",
        flow="stage-flow",
    )

    delivery = primary_item_delivery_by_session(conn, [{"session_id": "s1"}])["s1"]
    assert delivery["run_id"] == "run-prod"
    assert delivery["live"] is True


def test_an_item_no_release_carries_reports_nothing(test_db) -> None:
    assert primary_item_delivery_by_session(_connection(test_db), [{"session_id": "s1"}]) == {}

