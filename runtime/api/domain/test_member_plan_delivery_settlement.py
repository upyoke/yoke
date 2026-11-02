"""Accepted member-owned plans permit collective delivery settlement."""

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    _project,
    _member_at_release_wait,
)
from runtime.api.domain.test_deployment_qa_plan_groups import _attach
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_A
from runtime.api.domain.test_no_obligation_member_close_out import _landing_evidence
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_stage_entry import set_current_stage
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

MEMBER = 9827
RUN = "run-member-plan-settlement"
STAGE = "item-qa"


@pytest.mark.parametrize("accepted", [False, True])
def test_single_attacher_settles_only_after_member_qa_passes(
    test_db, monkeypatch, accepted
):
    _isolate_status_effects(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.sync_item_to_github", lambda _item: ""
    )
    _project(test_db)
    _member_at_release_wait(test_db, MEMBER)
    _landing_evidence(test_db, MEMBER)
    plan = _plan(test_db)
    stages = _stages(plan)
    stages[1].pop("cases")
    _seed_run(
        test_db, run_id=RUN, stages=stages, members=(), existing_members=(MEMBER,)
    )
    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", (f"flow-{RUN}", MEMBER)
    )
    _attach(test_db, MEMBER, plan)
    set_current_stage(test_db, RUN, STAGE)
    test_db.commit()
    subject = dict(
        deployment_run_id=RUN, deployment_stage=STAGE, deployment_member_item_id=MEMBER
    )
    materialize_deployment_qa_stage(test_db, **subject)
    if accepted:
        execution = begin_plan_execution(
            test_db, **subject, actor_id="2", session_id=HOLDER_A
        )
        _complete_case(test_db, execution)

    assert run_groups(test_db, [RUN], STAGE) == []
    assert satisfied_delivery_member(test_db, item_id=MEMBER, run_id=RUN) is accepted
    if not accepted:
        return
    assert cmd_update(RUN, "status", "succeeded") is None
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (RUN,)
        ).fetchone()[0]
        == "succeeded"
    )
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (MEMBER,)).fetchone()[0]
        == "done"
    )
