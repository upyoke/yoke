"""Relay-native failures retain private output without crossing the report wire."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_harness import session_relay
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_native_diagnostics import read_native_diagnostic
from yoke_harness.session_relay_runtime import (
    RelayAdapterResult,
    RelayPrivateDiagnostic,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _inventory() -> RelayInventory:
    return RelayInventory(
        relay_id=f"machine:{MACHINE_ID}",
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        project_ids=(10,),
        surface_versions={"claude-cli": "2.1.241"},
    )


def test_native_failure_reports_only_safe_reference_and_fingerprint(
    tmp_path: Path,
) -> None:
    calls = []
    job = {
        "job_kind": "wake",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
        "surface": "claude-cli",
        "project_id": 10,
        "native_instruction": "private instruction",
    }

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "job": job},
            )
        return SimpleNamespace(success=True, result={"state": "failed"})

    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=lambda _job: RelayAdapterResult(
            "failed",
            adapter_revision="claude-native-v2",
            evidence={
                "result_code": "native_exit",
                "surface": "claude-cli",
                "exit_code": 1,
            },
            private_diagnostic=RelayPrivateDiagnostic(
                "process_exit",
                error_step="session_lookup",
                stdout=b"private stdout body",
                stderr=b"actual native stderr",
            ),
        ),
        clock=lambda: 1000.0,
    )

    assert outcome.state == "reported"
    report = calls[1]["payload"]
    evidence = report["evidence"]
    assert evidence["diagnostic_availability"] == "relay_local"
    assert evidence["native_error_class"] == "process_exit"
    assert evidence["native_error_step"] == "session_lookup"
    assert len(evidence["native_error_sha256"]) == 64
    assert evidence["native_diagnostic_ref"].startswith("nd-")
    assert isinstance(evidence["diagnostic_expires_at"], int)
    assert "private stdout body" not in repr(report)
    assert "actual native stderr" not in repr(report)
    assert "private instruction" not in repr(report)

    payload = read_native_diagnostic(
        evidence["native_diagnostic_ref"],
        state_dir=tmp_path,
        now=1001,
    )
    assert b"private stdout body" in payload
    assert b"actual native stderr" in payload


def test_storage_failure_reports_unavailable_without_raw_streams(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from yoke_harness.session_relay_native_diagnostics import NativeDiagnosticError

    def unavailable(*_args, **_kwargs):
        raise NativeDiagnosticError("private filesystem detail")

    monkeypatch.setattr(session_relay, "store_native_diagnostic", unavailable)
    result = session_relay._retain_private_diagnostic(
        RelayAdapterResult(
            "failed",
            evidence={"result_code": "native_exit"},
            private_diagnostic=RelayPrivateDiagnostic(
                "process_exit",
                error_step="private-step-name",
                stderr=b"private native failure",
            ),
        ),
        state_dir=tmp_path,
    )

    assert result.evidence == {
        "result_code": "native_exit",
        "native_error_class": "process_exit",
        "native_error_step": "native_command",
        "diagnostic_availability": "unavailable",
    }
    assert result.private_diagnostic is None
    assert "private native failure" not in repr(result)
    assert "private filesystem detail" not in repr(result)
