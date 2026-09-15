"""Ephemeral run bookkeeping stays on the selected control-plane transport."""

from __future__ import annotations

from unittest.mock import Mock, patch

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import deploy_ephemeral_files


def _response(function: str, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=function,
        version="v1",
        request_id=f"{function}-request",
        result=result,
    )


def test_tracking_creates_and_updates_through_registered_operations() -> None:
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == "ephemeral_env.create":
            return _response(kwargs["function_id"], {"env_id": 27})
        return _response(kwargs["function_id"], {"updated": True})

    with patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        side_effect=dispatch,
    ), patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=AssertionError("client-local database opened"),
    ):
        deploy_ephemeral_files.track(
            "externalwebapp",
            "release-preview",
            {"status": "running", "url": "https://preview.example"},
            "EXT-27",
        )

    assert [call["function_id"] for call in calls] == [
        "ephemeral_env.create",
        "ephemeral_env.update",
        "ephemeral_env.update",
    ]
    assert calls[0]["payload"] == {
        "project": "externalwebapp",
        "branch": "release-preview",
        "item": "EXT-27",
    }
    assert calls[1]["payload"] == {
        "env_id": 27,
        "field": "status",
        "value": "running",
    }


def test_ephemeral_events_preserve_target_environment() -> None:
    policy = Mock(project="externalwebapp")
    with patch(
        "yoke_core.domain.deploy_pipeline_events.emit_deployment_event"
    ) as emit:
        deploy_ephemeral_files.emit_ephemeral_event(
            "EphemeralReady", policy, "release-preview", {"run_id": "run-1"}
        )

    assert emit.call_args.kwargs["project"] == "externalwebapp"
    assert emit.call_args.kwargs["environment"] == "ephemeral-release-preview"
