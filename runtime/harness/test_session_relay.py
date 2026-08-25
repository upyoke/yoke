"""Client relay inventory, adapter, scheduling, and redaction tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config.machine_config import ConfiguredProject
from yoke_harness import session_relay
from yoke_harness import session_relay_inventory as inventory_module
from yoke_harness import session_relay_runtime as runtime
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_runtime import RelayAdapterResult
from yoke_harness.session_relay_schedule import (
    poll_is_due,
    record_next_poll,
    relay_run_lock,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("waiting", "waiting"),
        ("idle_timeout", "idle_timeout"),
        (" waiting ", None),
        ("other", None),
        (None, None),
    ],
)
def test_execution_context_parses_only_authorized_wake_modes(
    monkeypatch,
    tmp_path: Path,
    raw,
    expected,
) -> None:
    monkeypatch.setattr(
        runtime.machine_config,
        "configured_projects",
        lambda **_kwargs: [ConfiguredProject(tmp_path, 10, {})],
    )

    context = runtime.execution_context({"project_id": 10, "wake_mode": raw})

    assert context.wake_mode == expected


def _inventory() -> RelayInventory:
    return RelayInventory(
        relay_id=f"machine:{MACHINE_ID}",
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        project_ids=(10,),
        surface_versions={"codex-cli": "0.148.0a15"},
    )


def test_inventory_reports_versions_and_project_ids_without_checkout_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(inventory_module, "ensure_machine_id", lambda: MACHINE_ID)
    monkeypatch.setattr(
        inventory_module.machine_config,
        "configured_projects",
        lambda **_kwargs: [ConfiguredProject(tmp_path, 10, {})],
    )
    monkeypatch.setattr(
        inventory_module,
        "local_handshake_version",
        lambda: "0.1.1",
    )

    observed = inventory_module.collect_inventory(
        cli_probe=lambda command: "1.2.3" if command[0] == "codex" else None,
        app_probe=lambda path: "2.3.4" if "Cursor" in str(path) else None,
    )

    payload = observed.claim_payload()
    assert payload["projects"] == [10]
    assert payload["surfaces"] == {
        "codex-cli": "1.2.3",
        "cursor-desktop": "2.3.4",
    }
    assert str(tmp_path) not in repr(payload)


def test_single_surface_version_uses_matching_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        inventory_module,
        "probe_app_version",
        lambda path: "26.818.31338" if "ChatGPT" in str(path) else None,
    )

    assert inventory_module.probe_surface_version("codex-desktop") == "26.818.31338"
    assert inventory_module.probe_surface_version("unknown-surface") is None


def test_registered_adapter_receives_attestation_only_in_dedicated_field(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime.reset_relay_adapters_for_tests()
    monkeypatch.setattr(
        runtime.machine_config,
        "configured_projects",
        lambda **_kwargs: [ConfiguredProject(tmp_path, 10, {})],
    )
    seen = []
    runtime.register_relay_adapter(
        "codex-cli",
        lambda context: (
            seen.append(context)
            or RelayAdapterResult("native_created", native_session_id="native-1")
        ),
    )

    result = runtime.run_registered_job(
        {
            "job_kind": "launch",
            "job_id": "launch-1",
            "lease_id": "lease-1",
            "surface": "codex-cli",
            "surface_version": "0.148.0-alpha.15",
            "project_id": 10,
            "native_instruction": "opaque bootstrap",
            "requested_model": "gpt-5.6",
            "presentation": "focused",
            "launch_attestation": "secret-attestation",
        }
    )

    assert result.result_code == "native_created"
    assert seen[0].native_instruction == "opaque bootstrap"
    assert seen[0].surface_version == "0.148.0-alpha.15"
    assert seen[0].requested_model == "gpt-5.6"
    assert seen[0].presentation == "focused"
    assert seen[0].launch_attestation == "secret-attestation"
    assert "secret-attestation" not in repr(seen[0])


def test_missing_adapter_is_registered_lazily_before_job_execution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from yoke_harness import session_relay_defaults

    runtime.reset_relay_adapters_for_tests()
    monkeypatch.setattr(
        runtime.machine_config,
        "configured_projects",
        lambda **_kwargs: [ConfiguredProject(tmp_path, 10, {})],
    )
    registered = []

    def register(surface):
        registered.append(surface)
        runtime.register_relay_adapter(
            surface,
            lambda _context: RelayAdapterResult("native_created", "native-1"),
        )
        return True

    monkeypatch.setattr(
        session_relay_defaults,
        "register_default_relay_adapter",
        register,
    )

    result = runtime.run_registered_job(
        {
            "job_kind": "launch",
            "job_id": "11111111-1111-4111-8111-111111111111",
            "lease_id": "lease-1",
            "surface": "codex-cli",
            "surface_version": "0.148.0-alpha.15",
            "project_id": 10,
            "native_instruction": "opaque bootstrap",
            "launch_attestation": "secret-attestation",
        }
    )

    assert registered == ["codex-cli"]
    assert result.result_code == "native_created"
    assert result.native_session_id == "native-1"


def test_serve_once_reports_sanitized_result_and_honors_server_backoff(
    tmp_path: Path,
) -> None:
    calls = []
    job = {
        "job_kind": "launch",
        "job_id": "launch-1",
        "lease_id": "lease-1",
        "surface": "codex-cli",
        "project_id": 10,
        "native_instruction": "opaque bootstrap",
        "launch_attestation": "secret-attestation",
    }

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            return SimpleNamespace(
                success=True,
                result={
                    "state": "active",
                    "next_poll_seconds": 300,
                    "jobs": [job],
                },
            )
        return SimpleNamespace(success=True, result={"state": "awaiting_registration"})

    first = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=lambda _job: RelayAdapterResult(
            "native_created",
            native_session_id="native-1",
            adapter_revision="adapter-1",
            evidence={
                "duration_ms": 12,
                "surface": "codex-cli",
                "token": "must-not-cross-wire",
                "nested": {"body": "must-not-cross-wire"},
            },
        ),
        clock=lambda: 1000.0,
    )
    second = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1001.0,
    )

    assert first.state == "reported"
    assert second.state == "backoff"
    assert len(calls) == 4
    reports = [call["payload"] for call in calls[1:]]
    assert [report["result"] for report in reports] == [
        "progress",
        "progress",
        "native_created",
    ]
    report = reports[-1]
    assert report["native_id"] == "native-1"
    assert report["evidence"] == {
        "duration_ms": 12,
        "native_launch_phase": "native_running",
        "surface": "codex-cli",
    }
    assert "native_instruction" not in report
    assert "launch_attestation" not in report
    assert "secret-attestation" not in repr(report)
    assert "must-not-cross-wire" not in repr(report)


def test_next_server_poll_adopts_a_shorter_cadence(tmp_path: Path) -> None:
    poll_seconds = iter((60, 5, 5))
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            result={"state": "active", "next_poll_seconds": next(poll_seconds)},
        )

    first = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1000.0,
    )
    early = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1005.0,
    )
    changed = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1060.0,
    )
    next_short_poll = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1065.0,
    )

    assert first.next_poll_seconds == 60
    assert early.state == "backoff"
    assert changed.next_poll_seconds == 5
    assert next_short_poll.state == "active"
    assert len(calls) == 3


def test_relay_lock_is_non_overlapping(tmp_path: Path) -> None:
    with relay_run_lock(tmp_path) as first:
        with relay_run_lock(tmp_path) as second:
            assert first is True
            assert second is False


def test_environment_locks_and_backoff_state_coexist(tmp_path: Path) -> None:
    prod_state = tmp_path / "relay"
    stage_state = tmp_path / "relay-instances" / "stage-hash"

    with relay_run_lock(prod_state) as prod:
        with relay_run_lock(stage_state) as stage:
            assert prod is True
            assert stage is True

    record_next_poll(60, prod_state, started_at=1000.0, now=1000.0)
    assert not poll_is_due(prod_state, now=1001.0)
    assert poll_is_due(stage_state, now=1001.0)
    record_next_poll(5, stage_state, started_at=1000.0, now=1000.0)
    assert not poll_is_due(stage_state, now=1001.0)
    assert poll_is_due(stage_state, now=1005.0)
