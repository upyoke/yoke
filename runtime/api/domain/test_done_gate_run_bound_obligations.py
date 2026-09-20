"""The done gate sees run-bound obligations scoped to an item as member."""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401,F811
)
from runtime.api.domain.qa_gate_test_support import qa_db  # noqa: F401
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import backlog
from yoke_core.domain.deployment_qa_source_obligation import unsatisfied_blocking
from yoke_core.domain.mutations import GateContext, ItemState, prepare_update
from yoke_core.domain.qa_gate_definitions import (
    QA_NONSETTLING_TERMINAL_STATUSES,
    QA_SETTLING_TERMINAL_STATUSES,
    GateTarget,
    status_settles_blocking_qa,
)
from yoke_core.domain.qa_gates import check_done_gate
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

RUN_ID = "run-20260920-001"
ITEM_ID = 10
SISTER_ID = 11


def _seed_run_bound(path, *, item_id: int, run_id: str = RUN_ID) -> int:
    conn = _conn(path)
    row = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        qa_kind="plan_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
        deployment_stage="qa",
        deployment_member_item_id=item_id,
    )
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _item() -> ItemState:
    return ItemState(
        id=42,
        title="Test item",
        status="release",
        priority="medium",
        frozen=False,
        project="yoke",
        workflow=builtin_workflow_runtime("issue"),
    )


def _update(
    tmp_db,
    *,
    item_id: int,
    value: str,
    qa_bypass: bool = False,
    resolution: str | None = None,
):
    out = io.StringIO()
    with _patch_externals(), mock.patch.dict(
        os.environ,
        {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
    ):
        return backlog.execute_update(
            item_id=item_id,
            field="status",
            value=value,
            resolution=resolution,
            done_nonce_verified=value == "done",
            qa_bypass=qa_bypass,
            out=out,
        )


class TestTerminalSettlementDecision:
    def test_done_settles_and_engine_terminals_do_not(self):
        assert QA_SETTLING_TERMINAL_STATUSES == frozenset({"done"})
        assert QA_NONSETTLING_TERMINAL_STATUSES == frozenset(
            {"cancelled", "stopped"}
        )
        assert status_settles_blocking_qa("done")
        assert not status_settles_blocking_qa("cancelled")
        assert not status_settles_blocking_qa("stopped")

    def test_prepare_update_cancelled_ignores_unsatisfied_count(self):
        item = _item()
        gate = GateContext(unsatisfied_all_blocking=1, done_nonce_verified=True)
        for status in ("cancelled", "stopped"):
            result = prepare_update(
                item=item, field_name="status", value=status, gate=gate
            )
            assert result.success is True, status


class TestCheckDoneGateRunBound:
    def test_names_run_and_requirement(self, qa_db):
        conn = connect_test_db(qa_db)
        conn.execute(
            "INSERT INTO qa_requirements ("
            "item_id, deployment_run_id, deployment_stage, "
            "deployment_member_item_id, qa_kind, qa_phase, blocking_mode, "
            "created_at) VALUES ("
            "NULL, %s, %s, %s, 'plan_case', 'post_deploy', 'blocking', %s"
            ")",
            (RUN_ID, "qa", 42, "2026-04-20T00:00:00Z"),
        )
        conn.commit()
        req_id = int(conn.execute("SELECT id FROM qa_requirements").fetchone()[0])
        conn.close()

        result = check_done_gate(GateTarget(item_id=42), qa_db)
        joined = "\n".join(result.errors)
        assert not result.passed
        assert RUN_ID in joined
        assert f"#{req_id}" in joined

    def test_another_members_row_is_not_this_items_set(self, qa_db):
        conn = connect_test_db(qa_db)
        conn.execute(
            "INSERT INTO qa_requirements ("
            "item_id, deployment_run_id, deployment_stage, "
            "deployment_member_item_id, qa_kind, qa_phase, blocking_mode, "
            "created_at) VALUES ("
            "NULL, %s, %s, %s, 'plan_case', 'post_deploy', 'blocking', %s"
            ")",
            (RUN_ID, "qa", 99, "2026-04-20T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        result = check_done_gate(GateTarget(item_id=42), qa_db)
        joined = "\n".join(result.errors)
        assert not result.passed
        assert any("GATE_QA_REQUIREMENTS_EMPTY" in error for error in result.errors)
        assert RUN_ID not in joined


class TestExecuteUpdateRunBound:
    def test_done_refuses_and_names_run(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=ITEM_ID, status="release")
        req_id = _seed_run_bound(tmp_db, item_id=ITEM_ID)
        result = _update(tmp_db, item_id=ITEM_ID, value="done")
        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_DONE"
        assert RUN_ID in result["error"]
        assert f"#{req_id}" in result["error"]
        assert _item_field(tmp_db, ITEM_ID, "status") == "release"

    def test_repair_path_refuses_with_qa_bypass_false(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=ITEM_ID, status="release")
        req_id = _seed_run_bound(tmp_db, item_id=ITEM_ID)
        result = _update(tmp_db, item_id=ITEM_ID, value="done", qa_bypass=False)
        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_DONE"
        assert RUN_ID in result["error"]
        assert f"#{req_id}" in result["error"]

    def test_cancelled_does_not_settle(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=ITEM_ID, status="release")
        _seed_run_bound(tmp_db, item_id=ITEM_ID)
        result = _update(
            tmp_db, item_id=ITEM_ID, value="cancelled", resolution="abandoned"
        )
        assert result["success"] is True, result
        assert _item_field(tmp_db, ITEM_ID, "status") == "cancelled"

    def test_stopped_does_not_settle(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=ITEM_ID, status="release")
        _seed_run_bound(tmp_db, item_id=ITEM_ID)
        result = _update(tmp_db, item_id=ITEM_ID, value="stopped")
        assert result["success"] is True
        assert _item_field(tmp_db, ITEM_ID, "status") == "stopped"

    def test_sister_member_without_own_row_is_not_blocked_by_count(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=ITEM_ID, status="release")
        _seed_item(tmp_db, id=SISTER_ID, status="release")
        _seed_run_bound(tmp_db, item_id=ITEM_ID)
        conn = _conn(tmp_db)
        try:
            own = unsatisfied_blocking(
                conn, item_id=ITEM_ID, target_status="done"
            )
            sister = unsatisfied_blocking(
                conn, item_id=SISTER_ID, target_status="done"
            )
        finally:
            conn.close()
        assert own.count == 1
        assert sister.count == 0
