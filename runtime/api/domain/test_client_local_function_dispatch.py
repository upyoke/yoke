"""Client-local function dispatch stays independent of remote DB authority."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_contracts.control_plane_locality import (
    RemoteControlPlaneConnectionError,
    remote_control_plane,
)
from yoke_core.domain.yoke_function_dispatch import dispatch_local


def _request(function: str, payload: dict | None = None) -> dict:
    return {
        "function": function,
        "actor": ActorContext(
            actor_id=None,
            session_id="client-local-test-session",
        ).model_dump(),
        "target": TargetRef(kind="global").model_dump(),
        "payload": payload or {},
    }


def test_packet_check_runs_locally_under_https_authority() -> None:
    with remote_control_plane():
        response = dispatch_local(_request("packets.check.run"))

    assert response.success is True
    assert response.result["seed_ok"] is True


def test_agent_check_runs_locally_under_https_authority(tmp_path) -> None:
    with remote_control_plane():
        response = dispatch_local(_request(
            "agents.render.check",
            {"target_root": str(tmp_path)},
        ))

    assert response.success is True
    assert response.result["target_root"] == str(tmp_path)
    assert response.result["drift"]


def test_non_client_local_function_keeps_control_plane_guard() -> None:
    with remote_control_plane():
        with pytest.raises(RemoteControlPlaneConnectionError):
            dispatch_local(_request("organizations.get"))
