"""Item-stage intake retargets the request to the run the selection names.

The holder may name the run with ``deployment_run_id``; it is handed to the
selection for validation and never reaches the deployment-run request.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import qa_item_deployment_request as intake
from yoke_core.domain import qa_item_stage_run_selection as selection
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


@pytest.fixture
def select(monkeypatch):
    chosen = Mock(return_value="run-chosen")
    monkeypatch.setattr(intake, "select_stage_run", chosen)
    monkeypatch.setattr(intake, "render_item_ref", lambda conn, item_id: MEMBER)
    return chosen


def test_item_stage_is_retargeted_to_the_selected_run(select):
    conn = Mock()
    resolved = intake.resolve_item_deployment_request(conn, _request())
    select.assert_called_once_with(
        conn, item_id=ITEM_ID, stage="item-qa", item_ref=MEMBER, plan=None,
        requested_run_id=None,
    )
    assert resolved.target.kind == "deployment_run"
    assert resolved.target.deployment_run_id == "run-chosen"
    assert resolved.payload == {"deployment_stage": "item-qa", "deployment_member": MEMBER}


def test_a_named_run_is_validated_and_dropped_from_the_payload(select):
    resolved = intake.resolve_item_deployment_request(
        Mock(), _request(deployment_run_id="run-named")
    )
    assert select.call_args.kwargs["requested_run_id"] == "run-named"
    assert "deployment_run_id" not in resolved.payload


def test_a_named_run_without_a_stage_is_refused(select):
    request = Request(
        target=TargetRef(kind="item", item_id=ITEM_ID, project_id="1"),
        payload={"transition_id": "release", "deployment_run_id": "run-named"},
    )
    with pytest.raises(QaPlanError, match="qa_item_run_scope_invalid"):
        intake.resolve_item_deployment_request(Mock(), request)
    select.assert_not_called()


def test_a_member_selector_is_refused_on_the_item_form(select):
    with pytest.raises(QaPlanError, match="qa_item_stage_scope_invalid"):
        intake.resolve_item_deployment_request(Mock(), _request(deployment_member="X-1"))


@pytest.mark.parametrize("shared", [False, True])
def test_explicit_plan_reaches_the_selection_and_keeps_plan_ownership(
    select, monkeypatch, shared
):
    from yoke_core.domain import deployment_qa_plan_ownership, qa_plan_retire

    plan = {"id": 7, "target_environment_id": 2}
    monkeypatch.setattr(qa_plan_retire, "resolve_plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        deployment_qa_plan_ownership,
        "plan_owners",
        lambda *a: {7: None if shared else ITEM_ID},
    )
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = ("example",)
    resolved = intake.resolve_item_deployment_request(conn, _request(plan="7"))
    assert select.call_args.kwargs["plan"] is plan
    assert resolved.target.deployment_run_id == "run-chosen"
    assert ("deployment_member" in resolved.payload) is not shared


def test_a_refusal_from_the_selection_reaches_the_caller(select):
    select.side_effect = selection.QaItemRunNotMember("qa_item_run_not_member: no")
    with pytest.raises(QaPlanError) as refused:
        intake.resolve_item_deployment_request(Mock(), _request(deployment_run_id="r"))
    assert refused.value.code == "qa_item_run_not_member"


def test_no_live_run_teaches_driver_owned_stage_creation(monkeypatch):
    from yoke_core.domain import deployment_item_flow_resolution as flows
    import uuid

    monkeypatch.setattr(selection, "open_stage_holds", lambda *a, **k: [])
    monkeypatch.setattr(selection, "_fresh_stage_runs", lambda *a, **k: [])
    monkeypatch.setattr(flows, "item_completion_flow", lambda conn, item_id: "release-flow")
    monkeypatch.setattr(uuid, "uuid4", lambda: "fresh-request")
    rows = iter([{"slug": "example"}, None])
    monkeypatch.setattr(selection, "query_one", lambda *a, **k: next(rows))
    with pytest.raises(selection.QaItemStageUnavailable) as error:
        selection.select_stage_run(
            object(), item_id=ITEM_ID, stage="item-qa", item_ref=MEMBER
        )
    message = str(error.value)
    assert "no live run holds or is executing 'item-qa'" in message
    assert (
        "yoke deployment-runs create example release-flow --environment stage "
        "--idempotency-key fresh-request"
    ) in message
    assert "does not authorize the item holder" in message


def test_item_stage_help_advertises_the_named_run():
    from yoke_cli.commands.qa_case import QA_PLAN_RUN_USAGE

    assert "--stage STAGE [--plan PLAN] [--deployment-run-id RUN]" in QA_PLAN_RUN_USAGE
