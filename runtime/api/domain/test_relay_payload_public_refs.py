"""Client relay payloads name items by public ref, never by an engine join key.

The client and HTTP boundaries refuse any payload key that is an internal
item join key, even when its value is None. Each relay site here builds its
payload the way it would over an https control plane, and the request must
pass that same public-item contract.
"""

from __future__ import annotations

import argparse

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_contracts.public_item_contract import public_item_request_error


@pytest.fixture
def relayed(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture every request the client hands the dispatcher."""
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            request_id="r",
            result={"rc": 0},
        )

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        fake,
    )
    return calls


def _contract_error(call: dict):
    target = call.get("target")
    request = FunctionCallRequest.model_validate(
        {
            "function": call["function_id"],
            "version": "v1",
            "target": target.model_dump() if target is not None else {"kind": "global"},
            "actor": {"actor_id": "test", "session_id": ""},
            "payload": call.get("payload") or {},
        }
    )
    return public_item_request_error(request)


def _override_args(item: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        claim_id=5,
        override_point="creation",
        integration_target="main",
        actor_id=1,
        actor_reason="operator approved",
        blocking_claim_id=None,
        blocking_path_targets=None,
        conflict_reason=None,
        item=item,
        project=None,
        session_id=None,
    )


@pytest.mark.parametrize("item", ["YOK-12", None])
def test_path_claim_override_relays_the_item_as_a_public_ref(relayed, item) -> None:
    from yoke_core.domain.path_claims_dispatch_override import _relay_override

    assert _relay_override(_override_args(item)) == 0
    payload = relayed[0]["payload"]
    assert payload.get("public_ref") == item
    assert "item_id" not in payload
    assert _contract_error(relayed[0]) is None


@pytest.mark.parametrize("item_ref", ["YOK-12", None])
def test_deployment_events_name_their_member_by_public_ref(relayed, item_ref) -> None:
    from yoke_core.domain.deploy_pipeline_events import emit_deployment_event

    emit_deployment_event(
        "DeploymentRunStageCompleted",
        event_kind="lifecycle",
        event_type="deployment_run",
        source_type="system",
        severity="STATUS",
        project="yoke",
        outcome="completed",
        context={},
        item_ref=item_ref,
    )
    payload = relayed[0]["payload"]
    assert payload.get("public_ref") == item_ref
    assert "item_id" not in payload
    assert _contract_error(relayed[0]) is None


def test_epic_task_status_relays_the_epic_as_a_public_ref(relayed) -> None:
    from yoke_core.engines.done_transition_runtime import _update_task_status_direct

    assert _update_task_status_direct("YOK-40", "1", "done", "") == 0
    assert relayed[0]["payload"]["epic_public_ref"] == "YOK-40"
    assert _contract_error(relayed[0]) is None
