"""Client relay inventory, adapter, scheduling, and redaction tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_cli.config.machine_config import ConfiguredProject
from yoke_harness import session_relay
from yoke_harness import session_relay_inventory as inventory_module
from yoke_harness import session_relay_runtime as runtime
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_runtime import RelayAdapterResult
from yoke_harness.session_relay_schedule import relay_run_lock


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


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
            "project_id": 10,
            "native_instruction": "opaque bootstrap",
            "launch_attestation": "secret-attestation",
        }
    )

    assert result.result_code == "native_created"
    assert seen[0].native_instruction == "opaque bootstrap"
    assert seen[0].launch_attestation == "secret-attestation"
    assert "secret-attestation" not in repr(seen[0])


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
                result={"state": "active", "next_poll_seconds": 300, "job": job},
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
    assert len(calls) == 2
    report = calls[1]["payload"]
    assert report["native_id"] == "native-1"
    assert report["evidence"] == {"duration_ms": 12, "surface": "codex-cli"}
    assert "native_instruction" not in report
    assert "launch_attestation" not in report
    assert "secret-attestation" not in repr(report)
    assert "must-not-cross-wire" not in repr(report)


def test_relay_lock_is_non_overlapping(tmp_path: Path) -> None:
    with relay_run_lock(tmp_path) as first:
        with relay_run_lock(tmp_path) as second:
            assert first is True
            assert second is False
