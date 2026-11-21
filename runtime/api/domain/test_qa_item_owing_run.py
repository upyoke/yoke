"""Item QA reaches the run that owes it when several live runs could answer.

The item's open requirement rows at the stage name the run (YOK-5401: a Stage
run holding none of them must not shadow the Production run holding them
all). With no rows yet, each case's own ``target_envs`` picks the run, not
its plan's header. A run holding the rows before reaching the stage is named
with its status and stage; no new deployment is suggested.
"""

from types import SimpleNamespace

import pytest

from yoke_core.domain import qa_item_stage_run_selection as selection
from yoke_core.domain.qa_item_stage_run_selection import StageRun

ITEM_ID = 42
PLAN = {"id": 7, "target_environment_id": 3}  # header: production
STAGE_RUN = {"id": "run-stage", "env": "stage"}
PROD_RUN = {"id": "run-prod", "env": "production"}


def _member(run, *, stage="item-qa", status="executing"):
    return {
        "id": run["id"],
        "status": status,
        "settling": False,
        "current_stage": stage,
    }


@pytest.fixture
def world(monkeypatch):
    """Patch run reads; tests set holds, member runs and the owed plans."""
    from yoke_core.domain import (
        deployment_item_completion_runs,
        deployment_qa_member_plans,
        qa_plan_case_definition,
    )

    state = SimpleNamespace(
        holds=[], runs=[], owed={}, cases=[], rows=set(), envs={}
    )
    monkeypatch.setattr(selection, "open_stage_holds", lambda *a, **k: state.holds)
    monkeypatch.setattr(
        deployment_item_completion_runs, "completion_runs", lambda *a, **k: state.runs
    )
    monkeypatch.setattr(
        deployment_item_completion_runs,
        "uncarried_supplemental_run",
        lambda *a: False,
    )
    monkeypatch.setattr(
        deployment_qa_member_plans,
        "members_plan_ids",
        lambda conn, items, run_id: {ITEM_ID: state.owed.get(run_id, set())},
    )
    monkeypatch.setattr(
        qa_plan_case_definition,
        "plans_cases",
        lambda conn, ids: {PLAN["id"]: state.cases},
    )
    envs = {STAGE_RUN["id"]: "stage", PROD_RUN["id"]: "production"}
    monkeypatch.setattr(selection, "_run_environment", lambda conn, run_id: envs[run_id])
    monkeypatch.setattr(selection, "_environment_name", lambda conn, env_id: "production")
    monkeypatch.setattr(
        selection, "_has_stage_rows", lambda conn, item, stage, run_id: run_id in state.rows
    )
    monkeypatch.setattr(selection, "_new_run_text", lambda *a: "qa_item_stage_unavailable: new")
    return state


def _select(plan=None, **kwargs):
    return selection.select_stage_run(
        object(), item_id=ITEM_ID, stage="item-qa", item_ref="EXAMPLE-42",
        plan=plan, **kwargs,
    )


def _hold(run, *, status="executing", stage="item-qa", ids=(1,)):
    return StageRun(run["id"], status, stage, run["env"], ids)


def test_production_holding_the_rows_answers_over_a_stage_run_without_them(world):
    world.holds = [_hold(PROD_RUN, ids=(11, 12))]
    world.runs = [_member(PROD_RUN), _member(STAGE_RUN)]
    assert _select() == "run-prod"


@pytest.mark.parametrize("plan", [None, PLAN])
def test_stage_only_case_under_a_production_plan_reaches_the_stage_run(world, plan):
    """No rows yet: the case's own target_envs, not the plan header, decides."""
    world.runs = [_member(PROD_RUN), _member(STAGE_RUN)]
    world.owed = {"run-stage": {PLAN["id"]}}
    world.cases = [{"case_key": "stage-smoke", "target_envs": ["stage"]}]
    assert _select(plan) == "run-stage"


def test_a_run_whose_rows_settled_yields_to_the_run_still_owing(world):
    world.runs = [_member(PROD_RUN), _member(STAGE_RUN)]
    world.owed = {"run-prod": {7}, "run-stage": {7}}
    world.rows = {"run-prod"}
    assert _select() == "run-stage"


def test_one_live_run_at_the_stage_answers(world):
    world.runs = [_member(STAGE_RUN)]
    world.rows = {"run-stage"}
    assert _select() == "run-stage"


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_only_live_runs_answer(world, status):
    world.runs = [_member(STAGE_RUN, status=status)]
    with pytest.raises(selection.QaItemStageUnavailable, match="new"):
        _select(PLAN)


def test_two_runs_owing_with_no_rows_are_refused_with_both_named(world):
    world.runs = [_member(PROD_RUN), _member(STAGE_RUN)]
    world.owed = {"run-prod": {7}, "run-stage": {7}}
    with pytest.raises(selection.QaItemStageAmbiguous) as refused:
        _select()
    message = str(refused.value)
    assert "run-prod (environment production, executing" in message
    assert "run-stage (environment stage, executing" in message
    assert "no requirements yet" in message


def test_two_runs_holding_rows_are_refused_with_their_requirements(world):
    world.holds = [_hold(PROD_RUN, ids=(11,)), _hold(STAGE_RUN, ids=(21, 22))]
    with pytest.raises(selection.QaItemStageAmbiguous) as refused:
        _select()
    message = str(refused.value)
    assert "run-prod (environment production" in message and "requirements 11" in message
    assert "run-stage (environment stage" in message and "requirements 21, 22" in message
    assert "--deployment-run-id RUN" in message


@pytest.mark.parametrize(
    ("status", "stage"), [("executing", "hosted-release"), ("created", "")]
)
def test_a_live_run_not_yet_at_the_stage_is_named_without_a_new_deployment(
    world, status, stage
):
    """YOK-5604: requirement 70736 sat on run-20261121-010 at hosted-release."""
    world.holds = [_hold({"id": "run-20261121-010", "env": "production"},
                         status=status, stage=stage, ids=(70736,))]
    with pytest.raises(selection.QaItemStageUnavailable) as refused:
        _select()
    message = str(refused.value)
    assert "held by live run run-20261121-010" in message
    assert f"{status} at stage {stage or 'none'!r}" in message
    assert "requirements 70736" in message
    assert "Wait for that run's 'item-qa' wake" in message
    assert "--deployment-run-id run-20261121-010" in message
    assert "deployment-runs create" not in message
    assert "Do not start a new deployment" in message


def test_no_live_run_suggests_a_new_deployment(world):
    with pytest.raises(selection.QaItemStageUnavailable, match="new"):
        _select()
