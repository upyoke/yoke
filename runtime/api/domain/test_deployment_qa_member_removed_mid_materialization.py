"""A member removed while dispatch prepares its QA is skipped by name."""

import pytest

from runtime.api.domain.test_deployment_qa_shared_plans import (
    RUN,
    _attach,
    _materialize,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_member_removal import remove_members_on

A, B, C = 9901, 9902, 9903


def _remove_during_selection(test_db, monkeypatch):
    from yoke_core.domain import deployment_qa_plan_selection as selection

    real = selection.selected_plans
    fired = []

    def selected(conn, subject, **kw):
        snapshots = real(conn, subject, **kw)
        # A concurrent `remove-item` commits after the subject was loaded
        # and before materialization takes the run row lock.
        if not fired and subject.get("member_item_id") == A:
            fired.append(A)
            remove_members_on(test_db, RUN, [A], reason="concurrent removal")
            test_db.commit()
        return snapshots

    monkeypatch.setattr(selection, "selected_plans", selected)
    return fired


def _seed(test_db, *, formed):
    plan_id = _plan(test_db)
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=(A, B, C))
    _attach(test_db, A, plan_id)
    _attach(test_db, B, plan_id)
    if formed:
        _materialize(test_db, B)


@pytest.mark.parametrize("formed", [False, True])
def test_dispatch_skips_a_member_removed_mid_materialization(
    test_db, monkeypatch, formed
):
    _seed(test_db, formed=formed)
    fired = _remove_during_selection(test_db, monkeypatch)
    stage = next(s for s in pinned_stages(test_db, RUN) if s["name"] == "item-qa")
    _code, message = materialize_and_gate_deployment_qa_stage(
        test_db, stage, run_id=RUN
    )
    assert fired == [A]
    assert "YOK-9901" not in message


def test_materialization_refuses_a_member_removed_before_the_run_lock(
    test_db, monkeypatch
):
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )

    _seed(test_db, formed=False)
    _remove_during_selection(test_db, monkeypatch)
    with pytest.raises(LookupError, match="^deployment_member_removed: YOK-9901"):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=A,
        )
