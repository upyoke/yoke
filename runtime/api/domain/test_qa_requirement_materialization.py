"""Executable copies, actionable drift, and resumable shared QA scopes."""

import json

import pytest

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    _begin,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.domain.test_qa_plan_case_currency import (
    _materialized,
    _correct_the_case,
)
from runtime.api.domain.test_qa_plan_standalone_execution import (
    _plan as standalone_plan,
    _begin as standalone_begin,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.qa_plan_attachments import materialize_for_item
from yoke_core.domain.qa_plan_case_currency import plan_drift_report, rows_behind_plan
from yoke_core.domain.qa_plan_case_definition import materialized_definition, plan_cases
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from runtime.api.fixtures.completed_delivery import seed_selected_requirement_run
from yoke_core.domain.qa_plan_execution_continuation import continuation_recipe
from yoke_core.domain.qa_plan_execution_store import select_plan_execution
from yoke_core.domain.qa_requirement_supersession import same_scope
from yoke_core.domain.qa_terminal_requirement_errors import _recovery_instruction


def test_bound_environment_without_case_selector_keeps_correction_scope(test_db):
    plan_id = _plan(test_db, "bound-correction")
    plan = dict(
        test_db.execute("SELECT * FROM qa_plans WHERE id=%s", (plan_id,)).fetchone()
    )
    case = plan_cases(test_db, plan_id)[0]
    assert not json.loads(case["target_envs"] or "[]")
    target = {"environment": {"name": "prod", "kind": "persistent_environment"}}
    definition = materialized_definition(
        plan=plan,
        case=case,
        qa_phase="post_deploy",
        baseline=None,
        baseline_position=1,
        transition_id=None,
        execution_target=target,
    )
    assert definition["target_env"] == "prod"
    assert same_scope({**definition, "target_env": "prod"}, definition) == []


def test_methodless_standing_requirement_is_not_copied(test_db):
    insert_item(test_db, id=9715, title="Standing acceptance", workflow_id="issue")
    source_id = _original_requirement(test_db, item_id=9715, method_id=None)
    plan_id = _plan(test_db, "executable-selection")
    seed_selected_requirement_run(
        test_db,
        run_id="run-executable-selection",
        item_id=9715,
        requirement_id=source_id,
    )
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-executable-selection",
        deployment_stage="member-qa",
        deployment_member_item_id=9715,
        agent_plan=str(plan_id),
    )
    assert len(result["created_requirement_ids"]) == 1
    assert not test_db.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s AND method_id IS NULL",
        ("run-executable-selection",),
    ).fetchall()
    assert (
        test_db.execute(
            "SELECT id FROM qa_requirements WHERE id=%s",
            (source_id,),
        ).fetchone()
        is not None
    )


@pytest.mark.parametrize("phase", ["verification", "post_deploy"])
def test_methodless_recovery_uses_head_bound_recording(phase):
    recipe = _recovery_instruction(
        {"id": 34, "qa_kind": "ac_verification", "qa_phase": phase}
    )
    assert "yoke qa run add --requirement-id 34" in recipe
    assert "--qa-kind ac_verification" in recipe
    assert "--verdict pass --raw-result" in recipe
    assert "qa case run" not in recipe


def test_group_walk_persists_requesting_member_for_resume(test_db):
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    execution = _begin(test_db, MEMBERS[0])
    # A second member resumes the group walk without replacing its requester.
    assert _begin(test_db, MEMBERS[1])["id"] == execution["id"]
    stored = select_plan_execution(test_db, execution["id"], lock=False)
    assert stored["deployment_member_item_id"] is None
    assert stored["requesting_member_item_id"] == MEMBERS[0]
    assert f"--resume-execution-id {stored['id']}" in continuation_recipe(
        test_db, stored
    )


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_finished_items_are_counted_without_stale_row_noise(test_db, status):
    plan_id, historical_id = _materialized(test_db, item_id=8612)
    insert_item(test_db, id=8613, title="Active proof", workflow_id="issue")
    active_id = materialize_for_item(
        test_db,
        item_id=8613,
        transition_id="implemented",
    )["created_requirement_ids"][0]
    test_db.execute("UPDATE items SET status=%s WHERE id=8612", (status,))
    test_db.commit()
    _correct_the_case(test_db, plan_id)
    report = plan_drift_report(test_db, plan_id)
    assert report["historical_requirements_excluded_count"] == 1
    assert [r.requirement_id for r in rows_behind_plan(test_db, plan_id)] == [active_id]
    assert report["requirements_behind_plan_count"] == 1
    assert test_db.execute(
        "SELECT id FROM qa_requirements WHERE id=%s", (historical_id,)
    ).fetchone()


@pytest.mark.parametrize("state", ["completed", "aborted", "error"])
def test_finished_standalone_walks_remain_history_without_drift_noise(test_db, state):
    plan = standalone_plan(test_db)
    execution = standalone_begin(test_db)
    test_db.execute(
        "UPDATE qa_plan_executions SET state=%s WHERE id=%s", (state, execution["id"])
    )
    test_db.commit()
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "first",
                "position": 1,
                "method_id": "command",
                "instructions": "Corrected command",
                "expected_outcome": "It passes",
                "method_config": {"command": "true"},
            }
        ],
    )
    report = plan_drift_report(test_db, plan["id"])
    assert report["requirements_behind_plan"] == []
    assert report["historical_requirements_excluded_count"] == 2
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE standalone_execution_id=%s",
            (execution["id"],),
        ).fetchone()[0]
        == 2
    )


def test_head_sha_cli_reaches_existing_recording_contract(monkeypatch):
    from yoke_cli.commands.adapters import qa_browser

    received = {}

    def dispatch(**kwargs):
        received.update(kwargs)
        return 0

    monkeypatch.setattr(qa_browser, "dispatch_and_emit", dispatch)
    assert (
        qa_browser.qa_run_add(
            [
                "--requirement-id",
                "34",
                "--performed-by",
                "agent",
                "--qa-kind",
                "ac_verification",
                "--verdict",
                "pass",
                "--head-sha",
                "a" * 40,
                "--raw-result",
                "All criteria checked",
            ]
        )
        == 0
    )
    assert received["payload"]["head_sha"] == "a" * 40
    assert received["payload"]["raw_result"] == "All criteria checked"


def test_bound_default_environment_is_stable_across_materialize_and_refresh(test_db):
    from runtime.api.domain.test_deployment_qa_stage_execution import _environment
    from yoke_core.domain.qa_plan_management import create_plan
    from yoke_core.domain.qa_plan_attachments import set_project_default
    from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item
    from yoke_core.domain.qa_plan_case_currency import plan_case_divergence

    _environment(test_db)
    plan = create_plan(
        test_db,
        project="yoke",
        slug="bound-default",
        name="Bound default",
        target_environment="stage",
    )
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "command",
                "method_id": "command",
                "instructions": "Run true",
                "expected_outcome": "It passes",
                "method_config": {"command": "true"},
            }
        ],
    )
    insert_item(
        test_db, id=9716, title="Default environment proof", workflow_id="issue"
    )
    set_project_default(
        test_db, plan_id=plan["id"], workflow_id="issue", transition_id="implemented"
    )
    first = materialize_for_item(test_db, item_id=9716, transition_id="implemented")
    requirement_id = first["created_requirement_ids"][0]
    again = materialize_for_item(test_db, item_id=9716, transition_id="implemented")
    assert (
        test_db.execute(
            "SELECT target_env FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()[0]
        is None
    )
    assert again["created_requirement_ids"] == []
    assert again["existing_requirement_ids"] == [requirement_id]
    refreshed = rematerialize_for_item(
        test_db, item_id=9716, transition_id="implemented"
    )
    assert refreshed["created_requirement_ids"] == []
    assert plan_case_divergence(test_db, requirement_id) is None
