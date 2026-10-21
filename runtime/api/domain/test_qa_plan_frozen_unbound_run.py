"""A run that froze an unbound plan keeps its cases after the plan is bound."""

import pytest

from runtime.api.domain.test_installer_campaign_plan_sync import (
    source_checkout as source_checkout,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _attach
from yoke_core.domain import qa_plan_source_revision as source_binding
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_retire import retire_plan

RUN = "run-frozen-unbound"
MEMBERS = (9931, 9932)


@pytest.fixture
def bound_after_freeze(test_db, source_checkout, monkeypatch):
    """The run freezes the plan unbound; a later merge binds the saved plan."""
    root, git = source_checkout
    monkeypatch.setattr(
        source_binding,
        "open_carried_work_source",
        lambda conn, project_id: LocalCheckoutSource(str(root)),
    )
    candidate = git(root, "rev-parse", "HEAD").stdout.strip()
    pid = _plan(test_db)
    test_db.execute("UPDATE projects SET default_branch='stable' WHERE id=1")
    stages = _stages(pid)
    stages[1].pop("cases")
    _seed_run(
        test_db, run_id=RUN, stages=stages, members=MEMBERS, release_lineage=candidate
    )
    for member in MEMBERS:
        _attach(test_db, member, pid)
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    test_db.commit()
    (root / "cases.json").write_text('["bound definitions"]\n')
    assert git(root, "commit", "-am", "Bind the plan").returncode == 0
    bound = git(root, "rev-parse", "HEAD").stdout.strip()
    test_db.execute(
        "UPDATE qa_plans SET source_revision=%s WHERE id=%s", (bound, pid)
    )
    test_db.commit()
    return pid


def test_frozen_unbound_plan_keeps_settling_after_binding(
    test_db, bound_after_freeze
):
    for member in MEMBERS:
        status = deployment_qa_stage_status(
            test_db,
            run_id=RUN,
            stage_name="item-qa",
            member_item_id=member,
            notify_acceptance=False,
        )
        assert status["outcome"] != "error"


def test_retract_and_retire_succeed_on_the_run(test_db, bound_after_freeze):
    pid = bound_after_freeze
    for member in MEMBERS:
        retract_plan_from_item(
            test_db,
            item_id=member,
            plan_id=pid,
            transition_id="release",
            reason="mis-scoped attachment",
            actor_id=1,
        )
    result = retire_plan(
        test_db,
        project="yoke",
        plan=str(pid),
        reason="superseded plan",
        actor_id=1,
    )
    assert result["retired_at"] is not None


def test_snapshot_without_source_field_still_refuses(test_db, bound_after_freeze):
    plan = {"id": bound_after_freeze, "project_id": 1}
    with pytest.raises(QaPlanError, match="qa_plan_source_snapshot_missing"):
        source_binding.require_candidate_plan(test_db, plan, RUN)
    # A frozen empty binding stands for its run.
    source_binding.require_candidate_plan(
        test_db, {**plan, "source_revision": None}, RUN
    )
