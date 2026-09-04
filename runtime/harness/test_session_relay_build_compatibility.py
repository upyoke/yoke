"""A source relay refuses work when its server build is older."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.transport import control_plane_payload, source_build_skew
from yoke_contracts.session_control.function_ids import (
    RELAY_CLAIM_FUNCTION_ID,
    RELAY_LIST_FUNCTION_ID,
)
from yoke_contracts.session_control.relay_health import RELAY_NEWER_THAN_SERVER
from yoke_harness import session_relay
from yoke_harness.session_relay_build_compatibility import (
    refresh_relay_build_compatibility,
)
from yoke_harness.session_relay_health import observe_relay_health
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_daemon import serve_forever
from yoke_harness.session_relay_outcomes import ServeOnceOutcome


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
LOCAL_REVISION = "a" * 40
SERVER_REVISION = "v0.1.1+launch.365"


@pytest.fixture(autouse=True)
def _clear_observed_server_build():
    control_plane_payload.observe_server_build("")
    yield
    control_plane_payload.observe_server_build("")


def _ahead() -> source_build_skew.BuildComparison:
    return source_build_skew.BuildComparison(
        source_build_skew.AHEAD,
        local_head=LOCAL_REVISION,
        server_build=SERVER_REVISION,
        ahead_by=30,
    )


def _inventory() -> RelayInventory:
    return RelayInventory(
        relay_id=f"machine:{MACHINE_ID}",
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="source",
        project_ids=(10,),
        surface_versions={"codex-cli": "1.2.3"},
    )


def test_stable_read_uses_handshake_to_persist_named_refusal(tmp_path: Path) -> None:
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        control_plane_payload.observe_server_build(SERVER_REVISION, _ahead())
        return SimpleNamespace(success=True)

    refusal = refresh_relay_build_compatibility(
        dispatch,
        state_dir=tmp_path,
        timeout_s=10,
    )

    assert refusal is not None
    assert calls[0]["function_id"] == RELAY_LIST_FUNCTION_ID
    assert calls[0]["payload"] == {"limit": 1}
    health = observe_relay_health(tmp_path)
    assert health["state"] == "refused"
    assert health["run_refusal"] == {
        "reason": RELAY_NEWER_THAN_SERVER,
        "local_revision": LOCAL_REVISION,
        "server_revision": SERVER_REVISION,
        "ahead_by": 30,
        "observed_at": health["run_refusal"]["observed_at"],
        "recovery": "deploy",
    }


def test_probe_does_not_reuse_an_observation_from_an_earlier_call(
    tmp_path: Path,
) -> None:
    control_plane_payload.observe_server_build(SERVER_REVISION, _ahead())

    refusal = refresh_relay_build_compatibility(
        lambda **_kwargs: SimpleNamespace(success=True),
        state_dir=tmp_path,
        timeout_s=10,
    )

    assert refusal is None
    assert observe_relay_health(tmp_path)["state"] == "healthy"


def test_refused_cycle_publishes_health_without_running_a_job(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == RELAY_LIST_FUNCTION_ID:
            control_plane_payload.observe_server_build(SERVER_REVISION, _ahead())
            return SimpleNamespace(success=True, result={"relays": [], "count": 0})
        return SimpleNamespace(
            success=False,
            error=SimpleNamespace(code="payload_invalid"),
        )

    monkeypatch.setattr(session_relay, "call_dispatcher", dispatch)

    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        runner=lambda _job: pytest.fail("a refused relay must not run jobs"),
        clock=lambda: 1000.0,
    )

    assert outcome.state == RELAY_NEWER_THAN_SERVER
    assert outcome.local_revision == LOCAL_REVISION
    assert outcome.server_revision == SERVER_REVISION
    assert outcome.recovery == "deploy"
    assert calls[0]["function_id"] == RELAY_LIST_FUNCTION_ID
    assert calls[-1]["function_id"] == RELAY_CLAIM_FUNCTION_ID
    assert calls[-1]["payload"]["health"]["state"] == "refused"


def test_equal_server_observation_clears_the_refusal(tmp_path: Path) -> None:
    def ahead_probe(**_kwargs):
        control_plane_payload.observe_server_build(SERVER_REVISION, _ahead())
        return SimpleNamespace(success=True)

    refresh_relay_build_compatibility(
        ahead_probe,
        state_dir=tmp_path,
        timeout_s=10,
    )

    def equal_probe(**_kwargs):
        control_plane_payload.observe_server_build(
            "v0.1.1+launch.366",
            source_build_skew.BuildComparison(
                source_build_skew.EQUAL,
                local_head=LOCAL_REVISION,
                server_build="v0.1.1+launch.366",
            ),
        )
        return SimpleNamespace(success=True)

    refresh_relay_build_compatibility(
        equal_probe,
        state_dir=tmp_path,
        timeout_s=10,
    )

    assert observe_relay_health(tmp_path)["state"] == "healthy"


def test_unknown_comparison_does_not_erase_a_grounded_refusal(tmp_path: Path) -> None:
    def ahead_probe(**_kwargs):
        control_plane_payload.observe_server_build(SERVER_REVISION, _ahead())
        return SimpleNamespace(success=True)

    refresh_relay_build_compatibility(
        ahead_probe,
        state_dir=tmp_path,
        timeout_s=10,
    )

    def unknown_probe(**_kwargs):
        control_plane_payload.observe_server_build(
            "v0.1.1+launch.366",
            source_build_skew.BuildComparison(
                source_build_skew.UNKNOWN,
                server_build="v0.1.1+launch.366",
                reason="server build commit is not present",
            ),
        )
        return SimpleNamespace(success=True)

    refresh_relay_build_compatibility(
        unknown_probe,
        state_dir=tmp_path,
        timeout_s=10,
    )

    assert observe_relay_health(tmp_path)["state"] == "refused"


def test_build_refusal_logs_named_reason_and_both_revisions(
    tmp_path: Path, caplog
) -> None:
    caplog.set_level(logging.WARNING, logger="yoke_harness.session_relay_failure_log")

    serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: ServeOnceOutcome(
            RELAY_NEWER_THAN_SERVER,
            60,
            error_code=RELAY_NEWER_THAN_SERVER,
            error_detail=(
                f"{RELAY_NEWER_THAN_SERVER}: relay revision aaaaaaaaaaaa is 30 "
                "commit(s) ahead of server revision v0.1.1+launch.365; "
                "recovery: deploy"
            ),
        ),
        stop_after_cycles=1,
        idle_tick_seconds=0,
        install_signals=False,
    )

    assert RELAY_NEWER_THAN_SERVER in caplog.text
    assert "aaaaaaaaaaaa" in caplog.text
    assert "v0.1.1+launch.365" in caplog.text
    assert "recovery: deploy" in caplog.text
