"""Item QA reaches the run that still owes it when a Stage and Production pair
both stand at item QA (PLAT-468 on run-20261116-017 and run-20261116-018).

Both ``yoke qa plan run --item`` forms, with and without ``--plan``, use one
selection: among member runs executing at the stage, the ones whose item QA
is not yet accepted owe it, and the oldest of those answers first.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deployment_qa_run_acceptance as standing
from yoke_core.domain import qa_item_deployment_request as intake

ITEM_ID = 42
PLAN_ID = 7
# completion_runs and qa_member_runs answer newest first.
PRODUCTION = {"id": "run-prod", "status": "executing", "current_stage": "item-qa"}
STAGE = {"id": "run-stage", "status": "executing", "current_stage": "item-qa"}


class Request(SimpleNamespace):
    def model_copy(self, *, update):
        return Request(**{**vars(self), **update})


def _request(**payload):
    return Request(
        target=TargetRef(kind="item", item_id=ITEM_ID, project_id="1"),
        payload={"deployment_stage": "item-qa", **payload},
    )


@pytest.fixture
def world(monkeypatch):
    """Patch the run reads; ``world.owing`` names the runs that owe the item."""
    from yoke_core.domain import deployment_qa_plan_ownership, qa_plan_retire

    state = SimpleNamespace(owing=set(), runs=[], asked=[])

    def item_qa(conn, *, run_id, item_id, current_stage):
        state.asked.append((run_id, item_id, current_stage))
        return SimpleNamespace(accepted=run_id not in state.owing)

    monkeypatch.setattr(standing, "current_item_qa", item_qa)
    monkeypatch.setattr(intake, "completion_runs", lambda *a, **k: state.runs)
    monkeypatch.setattr(intake, "qa_member_runs", lambda *a, **k: state.runs)
    monkeypatch.setattr(intake, "render_item_ref", lambda conn, item_id: "EXAMPLE-42")
    monkeypatch.setattr(
        qa_plan_retire,
        "resolve_plan",
        lambda *a, **k: {"id": PLAN_ID, "target_environment_id": None},
    )
    monkeypatch.setattr(
        deployment_qa_plan_ownership, "plan_owners", lambda *a: {PLAN_ID: ITEM_ID}
    )
    return state


def _resolve(plan: bool) -> str:
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = ("example",)
    request = _request(plan=str(PLAN_ID)) if plan else _request()
    return intake.resolve_item_deployment_request(conn, request).target.deployment_run_id


@pytest.mark.parametrize("plan", [False, True])
def test_item_form_reaches_the_owing_stage_run(world, plan):
    """Production has accepted; the Stage run still owes the item."""
    world.runs = [PRODUCTION, STAGE]
    world.owing = {"run-stage"}
    assert _resolve(plan) == "run-stage"


@pytest.mark.parametrize("plan", [False, True])
def test_item_form_reaches_the_owing_production_run(world, plan):
    world.runs = [PRODUCTION, STAGE]
    world.owing = {"run-prod"}
    assert _resolve(plan) == "run-prod"


@pytest.mark.parametrize("plan", [False, True])
def test_oldest_owing_run_answers_first(world, plan):
    world.runs = [PRODUCTION, STAGE]
    world.owing = {"run-prod", "run-stage"}
    assert _resolve(plan) == "run-stage"


@pytest.mark.parametrize("plan", [False, True])
@pytest.mark.parametrize("owes", [False, True])
def test_one_run_is_unchanged(world, plan, owes):
    world.runs = [STAGE]
    world.owing = {"run-stage"} if owes else set()
    assert _resolve(plan) == "run-stage"


def test_owing_is_asked_at_the_requested_stage(world):
    world.runs = [PRODUCTION, STAGE]
    _resolve(False)
    assert world.asked == [
        ("run-prod", ITEM_ID, "item-qa"),
        ("run-stage", ITEM_ID, "item-qa"),
    ]


def test_plan_form_keeps_a_delivered_member_when_none_is_at_the_stage(world):
    world.runs = [{"id": "run-done", "status": "succeeded", "current_stage": "done"}]
    assert _resolve(True) == "run-done"
    assert world.asked == []
