"""Plan-credit recovery waits for the target run's QA stage to open."""

import pytest

from yoke_core.domain import deployment_qa_plan_credit as credit
from yoke_core.domain import deployment_qa_plan_groups as groups
from yoke_core.domain import deployment_qa_plan_ownership as ownership
from yoke_core.domain import project_identity


@pytest.mark.parametrize("member_owned", [False, True])
@pytest.mark.parametrize("current", ["hosted-release", "acceptance-qa", "settlement"])
def test_recovery_waits_only_before_the_plan_stage(monkeypatch, member_owned, current):
    item_id, plan_id = 17, 29
    item_ref = f"DEMO-{item_id}"
    run_id, stage, slug = "run-target", "acceptance-qa", "storage-proof"
    monkeypatch.setattr(groups, "run_groups", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ownership,
        "plan_owners",
        lambda *args: {plan_id: item_id} if member_owned else {plan_id: None},
    )
    monkeypatch.setattr(project_identity, "render_item_ref", lambda *args: item_ref)
    monkeypatch.setattr(
        credit,
        "_stages",
        lambda *args: [
            {"name": name} for name in ("hosted-release", stage, "settlement")
        ],
    )

    miss = credit._miss(
        item_id,
        plan_id,
        slug,
        {"id": run_id, "current_stage": current},
        stage,
        "stage",
        conn=object(),
    )

    recovery = miss["recovery"]
    if current == "hosted-release":
        assert f"Wait for deployment run {run_id} to reach {stage}" in recovery
        assert f"current stage is {current}" in recovery
        assert "stage-wait notice will wake the holder" in recovery
        assert "yoke qa plan run" not in recovery
    elif member_owned:
        assert recovery == f"yoke qa plan run --item {item_ref} --stage {stage}"
    else:
        assert recovery == (
            f"yoke qa plan run --deployment-run-id {run_id} --stage {stage} --plan {slug}"
        )
    assert miss["deployment_run_id"] == run_id
    assert miss["deployment_stage"] == stage
    assert miss["target_env"] == "stage"
