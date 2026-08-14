"""Version-aware refusal for renamed fields in control-plane payloads."""

from __future__ import annotations

import pytest

from yoke_cli.transport import (
    control_plane_payload,
    https_engine_handshake,
    source_build_skew,
)
from yoke_core.domain import qa_case_execution


@pytest.fixture(autouse=True)
def _clear_observed_server_build():
    control_plane_payload.observe_server_build("")
    yield
    control_plane_payload.observe_server_build("")


def test_required_field_accepts_any_current_payload_contract() -> None:
    assert (
        control_plane_payload.required_field({"current_name": "value"}, "current_name")
        == "value"
    )


def test_older_server_case_payload_names_the_server_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_build = "v0.1.1+launch.209"
    comparison = source_build_skew.BuildComparison(
        source_build_skew.AHEAD,
        local_head="a" * 40,
        server_build=server_build,
        ahead_by=12,
    )
    monkeypatch.setattr(https_engine_handshake, "local_handshake_version", lambda: "")
    monkeypatch.setattr(
        source_build_skew,
        "compare_to_server_build",
        lambda *_args: comparison,
    )
    monkeypatch.setattr(
        source_build_skew,
        "compare_main_to_origin",
        lambda *_args: source_build_skew.OriginComparison(source_build_skew.EQUAL),
    )
    monkeypatch.setattr(https_engine_handshake, "_skew_warned", False)
    https_engine_handshake.observe_server_version(
        {https_engine_handshake.ENGINE_VERSION_HEADER: server_build.removeprefix("v")},
        (),
        https_engine_handshake.ServerHandshake(),
    )

    with pytest.raises(qa_case_execution.QaCaseExecutionError) as raised:
        qa_case_execution.execute_case_context(
            {"method_id": "command", "method_name": "Command"}
        )

    message = str(raised.value)
    assert server_build in message
    assert "required payload field 'runner_id'" in message
    assert "Deploy a server release" in message
    assert f"pin the client checkout to {server_build}" in message
    assert isinstance(
        raised.value.__cause__,
        control_plane_payload.ControlPlanePayloadError,
    )
