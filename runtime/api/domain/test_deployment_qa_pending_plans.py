"""Failed stage plans stop automatic capture until their live cases change."""

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import RUN, _seed
from runtime.api.domain.test_deployment_qa_stage_execution import _plan, _seed_run, _stages
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from runtime.api.fixtures.qa_declared_replacement_fixture import corrected_case, declare
from yoke_core.domain.deployment_qa_pending_plans import pending_stage_plans
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)


def seeded_plan(conn, scope):
    if scope == "item":
        plan_id = _seed(conn)
    else:
        plan_id = _plan(conn, "automatic-smoke")
        stages = _stages(plan_id)
        stages[1]["scope"] = "run"
        _seed_run(conn, run_id=RUN, stages=stages, members=())
    stage = _stages(plan_id)[1] | {"scope": scope}
    result, message = materialize_and_gate_deployment_qa_stage(conn, stage, run_id=RUN)
    assert result == -4, message
    pending = pending_stage_plans(conn, stage, RUN)
    assert len(pending) == 1
    requirement = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND plan_id=%s AND method_id IS NOT NULL ORDER BY id LIMIT 1",
        (RUN, plan_id),
    ).fetchone()[0]
    return stage, requirement, pending


@pytest.mark.parametrize("scope", ["run", "item"])
@pytest.mark.parametrize("verdict", ["fail", "error"])
def test_determinate_failure_never_returns_plan_to_driver(test_db, scope, verdict):
    stage, requirement, _ = seeded_plan(test_db, scope)
    record_case_verdict(test_db, requirement, verdict, evidence=True)
    for _ in range(2):
        assert pending_stage_plans(test_db, stage, RUN) == []
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


@pytest.mark.parametrize("scope", ["run", "item"])
def test_declared_replacement_can_capture_after_failed_predecessor(test_db, scope):
    stage, requirement, pending = seeded_plan(test_db, scope)
    record_case_verdict(test_db, requirement, "fail", evidence=True)
    assert pending_stage_plans(test_db, stage, RUN) == []
    replacement = corrected_case(test_db, failed_id=requirement, case_key="corrected")
    declare(test_db, requirement, "corrected", [replacement])
    assert pending_stage_plans(test_db, stage, RUN) == pending
    record_case_verdict(test_db, replacement, "fail", evidence=True)
    assert pending_stage_plans(test_db, stage, RUN) == []


@pytest.mark.parametrize("scope", ["run", "item"])
def test_latest_pass_replaces_old_failure_for_pending_selection(test_db, scope):
    stage, requirement, pending = seeded_plan(test_db, scope)
    record_case_verdict(test_db, requirement, "fail", evidence=True)
    record_case_verdict(test_db, requirement, "pass", evidence=True)
    assert pending_stage_plans(test_db, stage, RUN) == pending
