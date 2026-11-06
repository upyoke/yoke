"""Pinned Shepherd final-edge verdict checks, including rejected legacy evidence."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain import db_backend
from yoke_core.domain import shepherd_gate
from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)


@pytest.fixture
def tmp_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as path:
        yield path


def _open(path: str):
    return connect_test_db(path)


def _insert_verdict(
    conn: Any,
    public_ref: str,
    transition: str,
    verdict: str,
    worker: str = "architect",
    created_at: str = "2026-04-21T12:00:00Z",
) -> None:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO shepherd_verdicts (public_ref, transition, worker, verdict, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (public_ref, transition, worker, verdict, created_at),
    )
    conn.commit()


class TestShepherdGate:
    def test_modern_verdict_passes(self, tmp_db):
        """Gate passes when the modern shepherd verdict is present."""
        conn = _open(tmp_db)
        try:
            insert_item(
                conn,
                id=501,
                title="Modern epic",
                workflow_id="epic",
                status="planned",
                spec="body",
            )
            _insert_verdict(conn, "YOK-501", "planning_to_plan_drafted", "READY")
            result = shepherd_gate.check_gate(501, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.transition == "planning_to_plan_drafted"
        assert result.verdict == "READY"

    def test_modern_verdict_caveats_passes(self, tmp_db):
        """CAVEATS on the modern verdict is still accepted."""
        conn = _open(tmp_db)
        try:
            insert_item(
                conn,
                id=502,
                title="Epic with caveats",
                workflow_id="epic",
                status="planned",
                spec="body",
            )
            _insert_verdict(conn, "YOK-502", "planning_to_plan_drafted", "CAVEATS")
            result = shepherd_gate.check_gate(502, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.verdict == "CAVEATS"

    def test_unrelated_verdict_does_not_satisfy_binding(self, tmp_db):
        """A verdict for another edge cannot satisfy the pinned handoff."""
        conn = _open(tmp_db)
        try:
            insert_item(
                conn,
                id=503,
                title="Historical epic",
                workflow_id="epic",
                status="done",
                spec="body",
            )
            _insert_verdict(
                conn,
                "YOK-503",
                "planned_to_ready",
                "READY",
                created_at="2026-04-03T12:00:00Z",
            )
            result = shepherd_gate.check_gate(503, conn=conn)
        finally:
            conn.close()

        assert result.passed is False
        assert result.transition is None
        assert "planning_to_plan_drafted" in result.reason

    def test_no_verdict_blocks(self, tmp_db):
        """Absence of any qualifying verdict blocks the gate."""
        conn = _open(tmp_db)
        try:
            insert_item(
                conn,
                id=504,
                title="Unsigned epic",
                workflow_id="epic",
                status="planned",
                spec="body",
            )
            result = shepherd_gate.check_gate(504, conn=conn)
        finally:
            conn.close()

        assert result.passed is False
        assert result.transition is None
        assert result.verdict is None
        assert "planning_to_plan_drafted" in result.reason

    def test_rejected_verdict_does_not_satisfy(self, tmp_db):
        """REJECTED or other non-accepted verdicts do not satisfy the gate."""
        conn = _open(tmp_db)
        try:
            insert_item(
                conn,
                id=505,
                title="Rejected plan",
                workflow_id="epic",
                status="planned",
                spec="body",
            )
            _insert_verdict(conn, "YOK-505", "planning_to_plan_drafted", "REJECTED")
            result = shepherd_gate.check_gate(505, conn=conn)
        finally:
            conn.close()

        assert result.passed is False

    def test_modern_verdict_wins_over_legacy(self, tmp_db):
        """When both verdicts exist, the modern one is the reported transition."""
        conn = _open(tmp_db)
        try:
            insert_item(
                conn,
                id=506,
                title="Re-shepherded epic",
                workflow_id="epic",
                status="planned",
                spec="body",
            )
            _insert_verdict(
                conn,
                "YOK-506",
                "planned_to_ready",
                "READY",
                created_at="2026-04-03T12:00:00Z",
            )
            _insert_verdict(
                conn,
                "YOK-506",
                "planning_to_plan_drafted",
                "CAVEATS",
                created_at="2026-04-20T12:00:00Z",
            )
            result = shepherd_gate.check_gate(506, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.transition == "planning_to_plan_drafted"
        assert result.verdict == "CAVEATS"

    def test_latest_modern_verdict_wins(self, tmp_db):
        """Multiple modern verdicts — the newest (highest id) is returned."""
        conn = _open(tmp_db)
        try:
            insert_item(
                conn,
                id=507,
                title="Re-verdict epic",
                workflow_id="epic",
                status="planned",
                spec="body",
            )
            _insert_verdict(
                conn,
                "YOK-507",
                "planning_to_plan_drafted",
                "CAVEATS",
                created_at="2026-04-10T12:00:00Z",
            )
            _insert_verdict(
                conn,
                "YOK-507",
                "planning_to_plan_drafted",
                "READY",
                created_at="2026-04-20T12:00:00Z",
            )
            result = shepherd_gate.check_gate(507, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.verdict == "READY"


@pytest.mark.parametrize("writer", ["verdict", "caveat"])
def test_verdict_writes_reject_unknown_keys_without_rows(test_db, writer):
    from yoke_core.domain.shepherd_verdict_log import (
        ShepherdTransitionError,
        cmd_verdict,
        cmd_caveat_disposition,
    )

    item_id = 508
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    ref = f"YOK-{item_id}"
    with pytest.raises(
        ShepherdTransitionError, match="Valid keys:.*planning_to_plan_drafted"
    ):
        if writer == "verdict":
            cmd_verdict(test_db, ref, "planning-to-plan-drafted", "review", "READY")
        else:
            cmd_caveat_disposition(test_db, ref, "unknown", 1, 1, "caveat", "RESOLVED")
    for table in ("shepherd_verdicts", "caveat_dispositions"):
        assert test_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    cmd_verdict(test_db, ref, "planning_to_plan_drafted", "review", "READY")
    assert shepherd_gate.check_gate(item_id, conn=test_db).passed


def test_gate_recovery_is_reachable_after_planning(test_db):
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
    from yoke_core.domain.workflow_task_graph_status_gates import (
        evaluate_shepherd_verdict,
    )

    item_id = 509
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    result = evaluate_shepherd_verdict(
        conn=test_db,
        item_id=item_id,
        target_status="implementing",
        workflow=load_item_workflow_runtime(test_db, item_id),
    )
    for text in (
        shepherd_gate.check_gate(item_id, conn=test_db).reason,
        result["remediation_hint"],
    ):
        assert (
            f"yoke shepherd verdict --item YOK-{item_id} --transition planning_to_plan_drafted"
            in text
        )
        assert "Boss review" in text
        assert "Resume Shepherd" not in text
