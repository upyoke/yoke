# ruff: noqa: F811
"""A deployment run may not be stamped succeeded over unresolved blocking QA.

Blocking QA reaches a run through two independent tables, so each case
here exercises one of them against the real registered completion path
(``deployment_runs.cmd_update``) and the pipeline's report renderer. No
case touches a live run.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain import deployment_run_completion_preconditions as precond
from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    db_path,
)

FLOW = "externalwebapp-standard"
PROJECT = "externalwebapp"
FINAL_STAGE = "prod"


def _run_on_final_stage(db_path: str) -> str:
    """A run whose stages are delivered — only QA can still hold it."""
    run_id = dr.cmd_create_run(PROJECT, FLOW, db_path=db_path)
    dr.cmd_update(run_id, "current_stage", FINAL_STAGE, db_path=db_path)
    return run_id


def _add_flow_check(
    db_path: str,
    run_id: str,
    check_name: str,
    *,
    blocking: int = 1,
    status: str = "pending",
) -> None:
    dr.cmd_qa_add(run_id, check_name, "flow_default", blocking, db_path=db_path)
    if status != "pending":
        assert dr.cmd_qa_update(run_id, check_name, status, db_path=db_path) is None


def _add_plan_case(
    db_path: str,
    run_id: str,
    requirement_id: int,
    *,
    blocking_mode: str = "blocking",
    waived: bool = False,
    verdict: str | None = None,
) -> None:
    """Insert one run-bound plan requirement and its latest run, if any."""
    conn = _conn(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_requirements (
                id INTEGER PRIMARY KEY,
                deployment_run_id TEXT,
                qa_kind TEXT NOT NULL,
                qa_phase TEXT NOT NULL,
                blocking_mode TEXT NOT NULL DEFAULT 'blocking',
                waived_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_runs (
                id INTEGER PRIMARY KEY,
                qa_requirement_id INTEGER NOT NULL,
                performed_by TEXT NOT NULL DEFAULT 'agent',
                verdict TEXT,
                verdict_reason TEXT,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO qa_requirements "
            "(id, deployment_run_id, qa_kind, qa_phase, blocking_mode, waived_at) "
            "VALUES (%s, %s, 'smoke', 'post_deploy', %s, %s)",
            (
                requirement_id,
                run_id,
                blocking_mode,
                "2026-09-09T00:00:00Z" if waived else None,
            ),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO qa_runs (id, qa_requirement_id, verdict) "
                "VALUES (%s, %s, %s)",
                (requirement_id, requirement_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


class TestFlowDerivedChecks:
    """``deployment_run_qa`` rows seeded from the flow's stages."""

    @pytest.mark.parametrize("status", ["pending", "failed"])
    def test_unresolved_check_refuses_succeeded(self, db_path, status):
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "smoke-test", status=status)

        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        assert err is not None
        assert "blocking QA" in err
        assert "smoke-test" in err
        assert status in err
        assert dr.cmd_get(run_id, field="status", db_path=db_path) != "succeeded"

    def test_no_completion_stamp_while_unresolved(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "smoke-test")

        dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        assert not dr.cmd_get(run_id, field="completed_at", db_path=db_path)

    @pytest.mark.parametrize("status", ["passed", "waived"])
    def test_settled_check_completes(self, db_path, status):
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "smoke-test", status=status)

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None

    def test_nonblocking_check_never_holds_the_run(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "lighthouse", blocking=0)

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None

    def test_run_with_no_qa_completes(self, db_path):
        run_id = _run_on_final_stage(db_path)

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None

    def test_every_unresolved_check_is_named(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "smoke-test")
        _add_flow_check(db_path, run_id, "manual-acceptance", status="failed")

        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        assert err is not None
        assert "smoke-test" in err
        assert "manual-acceptance" in err

    def test_force_overrides_the_qa_hold(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "smoke-test")

        err = dr.cmd_update(
            run_id, "status", "succeeded", force=True, db_path=db_path
        )

        assert err is None

    def test_settling_then_re_driving_completes(self, db_path):
        """Re-driving after settlement is the resumable recovery."""
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "smoke-test")
        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        dr.cmd_qa_update(run_id, "smoke-test", "passed", db_path=db_path)

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None
        assert dr.cmd_get(run_id, field="status", db_path=db_path) == "succeeded"

    def test_repeated_completion_is_idempotent(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_flow_check(db_path, run_id, "smoke-test", status="passed")
        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None
        assert dr.cmd_get(run_id, field="status", db_path=db_path) == "succeeded"


class TestRunBoundPlanCases:
    """``qa_requirements`` rows keyed by ``deployment_run_id``."""

    @pytest.mark.parametrize("verdict", [None, "fail", "undetermined", "error"])
    def test_case_without_passing_run_refuses_succeeded(self, db_path, verdict):
        run_id = _run_on_final_stage(db_path)
        _add_plan_case(db_path, run_id, 4101, verdict=verdict)

        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        assert err is not None
        assert "#4101" in err
        assert dr.cmd_get(run_id, field="status", db_path=db_path) != "succeeded"

    def test_passing_run_completes(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_plan_case(db_path, run_id, 4102, verdict="pass")

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None

    def test_waived_case_completes(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_plan_case(db_path, run_id, 4103, waived=True)

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None

    def test_non_blocking_case_completes(self, db_path):
        run_id = _run_on_final_stage(db_path)
        _add_plan_case(db_path, run_id, 4104, blocking_mode="non_blocking")

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None

    def test_another_runs_case_never_holds_this_run(self, db_path):
        run_id = _run_on_final_stage(db_path)
        other_run_id = _run_on_final_stage(db_path)
        _add_plan_case(db_path, other_run_id, 4105)

        assert dr.cmd_update(run_id, "status", "succeeded", db_path=db_path) is None


class TestStagePreconditionsStillHold:
    """Moving the stage checks did not change what they refuse."""

    def test_failed_stage_still_refuses(self, db_path):
        run_id = dr.cmd_create_run(PROJECT, FLOW, db_path=db_path)
        dr.cmd_update(run_id, "current_stage", "deploy-failed", db_path=db_path)

        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        assert err is not None and "indicates failure" in err

    def test_non_final_stage_still_refuses(self, db_path):
        run_id = dr.cmd_create_run(PROJECT, FLOW, db_path=db_path)
        dr.cmd_update(run_id, "current_stage", "preview", db_path=db_path)

        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        assert err is not None and "not the final stage" in err

    def test_stage_refusal_leads_the_qa_refusal(self, db_path):
        """A failed stage is reported as such, not as unresolved QA."""
        run_id = dr.cmd_create_run(PROJECT, FLOW, db_path=db_path)
        dr.cmd_update(run_id, "current_stage", "deploy-failed", db_path=db_path)
        _add_flow_check(db_path, run_id, "smoke-test")

        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)

        assert err is not None and "indicates failure" in err


class TestPipelineWaitingReport:
    """What the pipeline prints when it stops short of finalization."""

    def test_report_names_each_obligation_and_the_recovery(self):
        lines = precond.awaiting_qa_report_lines(
            "run-20260909-001",
            ["check 'smoke-test' is pending", "requirement #7 (smoke): no passing run"],
        )

        assert lines[0].startswith(precond.AWAITING_QA_PREFIX)
        assert "2 blocking QA" in lines[0]
        assert lines[1] == "  - check 'smoke-test' is pending"
        assert lines[2] == "  - requirement #7 (smoke): no passing run"
        assert "re-drive run-20260909-001 to finalize" in lines[3]

    def test_report_does_not_claim_the_deploy_succeeded(self):
        lines = precond.awaiting_qa_report_lines("run-1", ["check 'x' is failed"])

        assert "succeeded" not in "\n".join(lines)
