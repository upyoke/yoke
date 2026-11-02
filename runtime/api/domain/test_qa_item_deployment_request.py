"""Item-stage intake selects the member currently executing the requested stage."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import qa_item_deployment_request as intake
from yoke_core.domain.qa_plan_management import QaPlanError

ITEM_ID = 42
MEMBER = "EXAMPLE-42"


class Request(SimpleNamespace):
    def model_copy(self, *, update):
        return Request(**{**vars(self), **update})


def _request(**payload):
    return Request(
        target=TargetRef(kind="item", item_id=ITEM_ID, project_id="1"),
        payload={"deployment_stage": "item-qa", **payload},
    )


def _run(name, status="executing", stage="item-qa"):
    return {"id": name, "status": status, "current_stage": stage}


@pytest.fixture
def members(monkeypatch):
    read = Mock()
    monkeypatch.setattr(intake, "completion_runs", read)
    monkeypatch.setattr(intake, "render_item_ref", lambda conn, item_id: MEMBER)
    return read


@pytest.mark.parametrize("active", ["stage", "prod"])
def test_current_stage_wins_over_newer_delivered_or_other_stage_runs(members, active):
    members.return_value = [
        _run("newest-prod", "succeeded"),
        _run("other-stage", stage="deploy"),
        _run(active),
        _run("older-active"),
    ]
    conn = Mock()
    resolved = intake.resolve_item_deployment_request(conn, _request())
    members.assert_called_once_with(conn, ITEM_ID, include_qa=True)
    assert resolved.target.kind == "deployment_run"
    assert resolved.target.deployment_run_id == active
    assert resolved.payload == {
        "deployment_stage": "item-qa",
        "deployment_member": MEMBER,
    }


@pytest.mark.parametrize(
    "runs",
    [
        [],
        [
            _run("finished", "succeeded"),
            _run("failed", "failed"),
            _run("cancelled", "cancelled"),
            _run("created", "created"),
            _run("other-stage", stage="deploy"),
        ],
    ],
)
def test_absent_active_member_teaches_driver_owned_stage_creation(
    members, monkeypatch, runs
):
    from yoke_core.domain import deployment_item_flow_resolution as flows

    members.return_value = runs
    monkeypatch.setattr(
        flows, "item_completion_flow", lambda conn, item_id: "release-flow"
    )
    monkeypatch.setattr(intake, "uuid4", lambda: "fresh-request")
    conn = Mock()
    conn.execute.return_value.fetchone.side_effect = [("example",), None]
    with pytest.raises(QaPlanError, match="qa_item_stage_unavailable") as error:
        intake.resolve_item_deployment_request(conn, _request())
    message = str(error.value)
    assert "Ask steering or the release driver" in message
    assert (
        "yoke deployment-runs create example release-flow --environment stage "
        "--idempotency-key fresh-request"
    ) in message
    assert "enrolls this item" in message and "before you retry QA" in message
    assert "does not authorize the item holder" in message


@pytest.mark.parametrize("shared", [False, True])
def test_explicit_plan_keeps_environment_and_plan_ownership_selection(
    members, monkeypatch, shared
):
    from yoke_core.domain import qa_plan_retire, deployment_qa_plan_ownership

    plan_id = 7
    monkeypatch.setattr(
        qa_plan_retire,
        "resolve_plan",
        lambda *a, **k: {
            "id": plan_id,
            "target_environment_id": 2,
        },
    )
    monkeypatch.setattr(
        deployment_qa_plan_ownership,
        "plan_owners",
        lambda *a: {
            plan_id: None if shared else ITEM_ID,
        },
    )
    select = Mock(return_value=_run("explicit"))
    monkeypatch.setattr(intake, "latest_qa_member_run", select)
    conn = Mock()
    conn.execute.return_value.fetchone.side_effect = [("example",), ("stage",)]
    resolved = intake.resolve_item_deployment_request(conn, _request(plan=str(plan_id)))
    select.assert_called_once_with(conn, item_id=ITEM_ID, target_env="stage")
    members.assert_not_called()
    assert resolved.target.deployment_run_id == "explicit"
    assert ("deployment_member" in resolved.payload) is not shared


def test_item_stage_help_advertises_explicit_plan():
    from yoke_cli.commands.qa_case import QA_PLAN_RUN_USAGE

    assert "--stage STAGE [--plan PLAN]" in QA_PLAN_RUN_USAGE


def test_recovery_uses_registered_stage_flow(members, monkeypatch):
    members.return_value = []
    conn = Mock()
    conn.execute.return_value.fetchone.side_effect = [("example",), ("stage-release",)]
    with pytest.raises(QaPlanError) as error:
        intake.resolve_item_deployment_request(conn, _request())
    assert "create example stage-release --environment stage" in str(error.value)
