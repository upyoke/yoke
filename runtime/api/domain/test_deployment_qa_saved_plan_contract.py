"""A later standing-plan publication cannot rewrite an older run's contract."""

import json

import pytest

from runtime.api.domain.test_installer_campaign_plan_sync import (
    source_checkout as source_checkout,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
    _complete_case,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _attach
from yoke_core.domain import qa_plan_source_revision as source_binding
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa
from yoke_core.domain.deployment_requirement_snapshots import (
    snapshot_member_requirements,
    requirement_selection,
)
from yoke_core.domain.qa_plan_management import replace_plan_cases, QaPlanError
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.deploy_target_occupancy import open_qa_lines

RUN = "run-saved-contract"
MEMBERS = (9921, 9922)


def _materialize(conn, member=MEMBERS[0]):
    return materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )


@pytest.fixture
def published(test_db, source_checkout, monkeypatch):
    root, git = source_checkout
    old = git(root, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(
        source_binding,
        "open_carried_work_source",
        lambda conn, project_id: LocalCheckoutSource(str(root)),
    )
    pid = _plan(test_db)
    test_db.execute("UPDATE projects SET default_branch='stable' WHERE id=1")
    test_db.execute("UPDATE qa_plans SET source_revision=%s WHERE id=%s", (old, pid))
    stages = _stages(pid)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=MEMBERS, release_lineage=old)
    for member in MEMBERS:
        _attach(test_db, member, pid)
    ids = _materialize(test_db)["created_requirement_ids"]
    _materialize(test_db, MEMBERS[1])
    # Preserve the complete selection frozen before its original execution.
    row = dict(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (ids[0],)
        ).fetchone()
    )
    test_db.commit()
    (root / "cases.json").write_text('["new definitions"]\n')
    assert git(root, "commit", "-am", "Publish new definitions").returncode == 0
    new = git(root, "rev-parse", "HEAD").stdout.strip()
    assert git(root, "push", "origin", "stable").returncode == 0
    replace_plan_cases(
        test_db,
        plan_id=pid,
        source_revision=new,
        cases=[
            {
                "case_key": key,
                "method_id": "command",
                "instructions": "new instruction",
                "expected_outcome": "new outcome",
                "method_config": {"command": "false"},
            }
            for key in ("command-smoke", "added-check")
        ],
    )
    return pid, ids, old, new, row


def test_old_contract_survives_publication_without_writes(test_db, published):
    pid, ids, old, new, before = published
    for member in MEMBERS:
        result = _materialize(test_db, member)
        assert result["created_requirement_ids"] == []
        assert result["existing_requirement_ids"] == ids
        answer = current_item_qa(
            test_db, run_id=RUN, item_id=member, current_stage="item-qa"
        )
        assert not answer.accepted
    assert open_qa_lines(test_db, RUN)
    after = dict(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (ids[0],)
        ).fetchone()
    )
    assert after == before
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0],
        actor_id="2",
        session_id="saved-contract",
    )
    assert [r["requirement_id"] for r in execution["roster"]] == ids
    _complete_case(test_db, execution)
    assert all(
        current_item_qa(
            test_db, run_id=RUN, item_id=m, current_stage="item-qa"
        ).accepted
        for m in MEMBERS
    )


def test_new_admission_freezes_current_definition(test_db, published):
    pid, ids, old, new, before = published
    stages = _stages(pid)
    stages[1].pop("cases")
    _seed_run(
        test_db,
        run_id="run-successor",
        stages=stages,
        members=(),
        existing_members=MEMBERS,
        release_lineage=new,
    )
    snapshot = json.loads(
        snapshot_member_requirements(
            test_db,
            run_id="run-successor",
            item_id=MEMBERS[0],
            selection_json=requirement_selection(),
        )
    )
    (plan,) = snapshot["plans"]
    assert plan["plan"]["source_revision"] == new
    assert [c["case_key"] for c in plan["cases"]] == ["command-smoke", "added-check"]
    with pytest.raises(QaPlanError, match="qa_plan_source_candidate_mismatch"):
        source_binding.require_candidate_plan(test_db, plan["plan"], RUN)
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-successor",
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0],
    )
    assert len(result["created_requirement_ids"]) == 2


def test_takeover_and_manual_removal_read_saved_contract(test_db, published):
    from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item
    from yoke_core.domain.deployment_run_target_takeover import (
        _waiting_run,
        _moving_members,
    )

    pid, ids, old, new, before = published
    test_db.execute(
        "UPDATE items SET status='release' WHERE id=ANY(%s)", (list(MEMBERS),)
    )
    test_db.commit()
    release_seeded_driver(test_db, RUN)
    new_run = dict(
        test_db.execute("SELECT * FROM deployment_runs WHERE id=%s", (RUN,)).fetchone()
    )
    new_run["id"] = "run-successor"
    waiting = _waiting_run(test_db, new_run)
    assert waiting["id"] == RUN
    assert [m["item_id"] for m in _moving_members(test_db, waiting, False)] == list(
        MEMBERS
    )
    message = cmd_remove_item(
        RUN, MEMBERS[1], reason="member rides successor", session_id="s", actor_id=1
    )
    assert "is not fully accepted" in message
    assert (
        dict(
            test_db.execute(
                "SELECT * FROM qa_requirements WHERE id=%s", (ids[0],)
            ).fetchone()
        )
        == before
    )


@pytest.mark.parametrize("shape", ["admitted", "materialized"])
def test_incomplete_historical_selection_refuses_without_writes(
    test_db, published, shape
):
    pid, ids, old, new, before = published
    for member in MEMBERS:
        snapshot = {
            "schema": 1,
            "plans": [],
            "requirements": [before] if shape == "admitted" else [],
        }
        test_db.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s WHERE run_id=%s AND item_id=%s",
            (json.dumps(snapshot, default=str), RUN, member),
        )
    # Exercise both historical private and shared shapes without reconstructing either.
    if shape == "materialized":
        test_db.execute(
            "UPDATE qa_requirements SET deployment_member_item_id=%s WHERE id=%s",
            (MEMBERS[0], ids[0]),
        )
    test_db.commit()
    with pytest.raises(QaPlanError, match="qa_frozen_plan_snapshot_incomplete"):
        _materialize(test_db)
    after = dict(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (ids[0],)
        ).fetchone()
    )
    if shape == "materialized":
        before = {**before, "deployment_member_item_id": MEMBERS[0]}
    assert after == before


def test_frozen_hosted_bridge_selects_original_cases_without_repointing(test_db):
    from runtime.api.domain.test_qa_requirement_target_rebind import _hosted_prod_pair
    from yoke_core.domain.deployment_qa_frozen_plan_selection import _member_plans
    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot

    hosted, own = _hosted_prod_pair(test_db)
    pid = _plan(test_db, "bridge-selection")
    test_db.execute(
        "UPDATE qa_plans SET target_environment_id=%s WHERE id=%s", (hosted, pid)
    )
    snapshot = _plan_snapshot(test_db, pid, project_id=1)
    snapshot["attachment"] = {"transition_id": "release", "qa_phase": "post_deploy"}
    snapshot["cases"][0]["id"] = (
        None  # Unavailable descriptive identity is not an executable key.
    )
    subject = {"member_item_id": MEMBERS[0], "member_snapshot": {"plans": [snapshot]}}
    target = {"project": {"id": 1}, "environment": {"id": own, "name": "prod"}}
    selected = _member_plans(test_db, subject, target=target)
    assert selected == [snapshot]
    assert selected[0]["plan"]["target_environment_id"] == hosted
    assert selected[0]["cases"][0]["target_envs"] == []
    assert (
        _member_plans(
            test_db,
            subject,
            target={**target, "environment": {"id": own + 100, "name": "other"}},
        )
        == []
    )


def test_authorized_withdrawal_excludes_incomplete_selection_before_validation(
    test_db, monkeypatch
):
    from yoke_core.domain import deployment_qa_frozen_plan_selection as selection

    monkeypatch.setattr(selection, "retracted_item_plan_ids", lambda conn, member: {71})
    subject = {
        "member_item_id": MEMBERS[0],
        "member_snapshot": {
            "plans": [{"attachment": {"qa_phase": "post_deploy"}, "plan": {"id": 71}}]
        },
    }
    assert (
        selection._member_plans(test_db, subject, target={"environment": {"id": 1}})
        == []
    )
