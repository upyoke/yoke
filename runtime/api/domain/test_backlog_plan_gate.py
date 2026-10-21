"""Status-write composition tests for the planned-transition QA gate."""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from typing import Optional

import pytest

from yoke_core.domain.backlog_updates_helpers import _run_authoritative_status_gate
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_gates import check_verification_gate
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    resolve_current_workflow_pin,
)
from yoke_core.domain.workflow_schema import ensure_workflow_schema
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog import (
    insert_epic_task,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)


_EXTRA_DDL = """
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,

    settings TEXT DEFAULT '{}',
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(project_id, type)
);

CREATE TABLE IF NOT EXISTS migration_audit (
    id INTEGER PRIMARY KEY,
    migration_name TEXT NOT NULL,
    status TEXT,
    state TEXT,
    model_name TEXT,
    project_id INTEGER
);
"""


@pytest.fixture
def helper_db(tmp_path: Path):
    db_file = tmp_path / "yoke.db"
    with pg_testdb.test_database() as conn:
        execute_schema_script(conn, _EXTRA_DDL)
        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
        conn.commit()
        yield conn, str(db_file)


def _seed_item(conn, item_id: int) -> None:
    insert_item(
        conn,
        id=item_id,
        status="plan-drafted",
        db_mutation_profile='{"state":"none"}',
    )
    workflow_id, version_id = resolve_current_workflow_pin(conn, "epic")
    conn.execute(
        "UPDATE items SET workflow_id = %s, workflow_version_id = %s WHERE id = %s",
        (workflow_id, version_id, item_id),
    )
    # The planned stage onward executes the task graph, so it must exist.
    insert_epic_task(conn, epic_id=item_id, task_num=1, status="plan-drafted")
    conn.commit()


def _seed_req(
    conn,
    item_id: int,
    *,
    verdict: Optional[str] = None,
    waived: bool = False,
    qa_kind: str = "simulation",
    workflow_transition_id: Optional[str] = None,
) -> int:
    extra = {}
    if workflow_transition_id is not None:
        extra["workflow_transition_id"] = workflow_transition_id
    req = insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind=qa_kind,
        qa_phase="verification",
        blocking_mode="blocking",
        waived_at="2026-04-25T00:00:00Z" if waived else None,
        **extra,
    )
    req_id = int(req["id"])
    if verdict is not None:
        insert_qa_run(
            conn,
            qa_requirement_id=req_id,
            verdict=verdict,
            qa_kind=qa_kind,
        )
    return req_id


def _status_gate(item_id: int, db_path: str, **overrides):
    args = {
        "item_id": item_id,
        "target_status": "planned",
        "db_path": db_path,
        "qa_bypass": False,
        "force": False,
    }
    args.update(overrides)
    return _run_authoritative_status_gate(**args)


class TestPlanSimulationGateComposition:
    def test_planned_with_unsatisfied_blocking_req_returns_unsatisfied(
        self, helper_db
    ) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 80)
        req_id = _seed_req(conn, 80, verdict="fail")
        outcome = _status_gate(80, db_path)
        assert outcome is not None
        assert outcome["error_code"] == "GATE_PLAN_SIM_UNSATISFIED"
        assert "Cannot advance to 'planned'" in outcome["error"]
        assert "no passing run" in outcome["error"]
        assert f"#{req_id}" in outcome["error"]

    def test_planned_with_satisfied_blocking_req_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 81)
        _seed_req(conn, 81, verdict="pass")
        assert _status_gate(81, db_path) is None

    def test_planned_with_no_requirements_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 82)
        assert _status_gate(82, db_path) is None

    def test_planned_with_waived_blocking_req_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 83)
        _seed_req(conn, 83, waived=True)
        assert _status_gate(83, db_path) is None

    def test_planned_with_qa_bypass_skips_gate(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 84)
        _seed_req(conn, 84, verdict="fail")
        assert _status_gate(84, db_path, qa_bypass=True) is None

    def test_planned_with_force_skips_gate(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 85)
        _seed_req(conn, 85, verdict="fail")
        assert _status_gate(85, db_path, force=True) is None

    def test_non_planned_target_skips_plan_gate(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 86)
        _seed_req(conn, 86, verdict="fail")
        outcome = _status_gate(86, db_path, target_status="refined-idea")
        assert outcome is None

    def test_planned_unavailable_helpers_return_unavailable(
        self, helper_db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 87)

        monkeypatch.delitem(sys.modules, "yoke_core.domain.qa_gates", raising=False)
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "yoke_core.domain" and "qa_gates" in (fromlist or ()):
                raise ImportError("simulated missing helpers")
            if name == "yoke_core.domain.qa_gates":
                raise ImportError("simulated missing helpers")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        outcome = _status_gate(87, db_path)
        assert outcome is not None
        assert outcome["error_code"] == "GATE_PLAN_SIM_UNAVAILABLE"
        assert "QA gate helpers are unavailable" in outcome["error"]

    def test_later_transition_verification_does_not_block_planned(
        self, helper_db
    ) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 90)
        _seed_req(
            conn,
            90,
            verdict="pass",
            qa_kind="simulation",
            workflow_transition_id="planned",
        )
        ac_id = _seed_req(
            conn,
            90,
            qa_kind="ac_verification",
            workflow_transition_id="reviewed-implementation",
        )
        assert _status_gate(90, db_path) is None
        review = check_verification_gate(GateTarget(item_id=90), db_path)
        assert not review.passed
        joined = "\n".join(review.errors)
        assert f"#{ac_id}" in joined
        assert "reviewed-implementation" in joined
