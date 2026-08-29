"""Relay-native failures retain private output without crossing the report wire."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_harness import session_relay
from yoke_harness import session_relay_diagnostic_retention as diagnostic_retention
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
                result={"state": "active", "next_poll_seconds": 60, "jobs": [job]},
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
                "identity_parse_failed",
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
    assert evidence["machine_id"] == MACHINE_ID
    assert evidence["relay_id"] == f"machine:{MACHINE_ID}"
    assert evidence["native_error_class"] == "identity_parse_failed"
    assert evidence["native_error_step"] == "session_lookup"
    assert len(evidence["native_error_sha256"]) == 64
    assert evidence["native_diagnostic_ref"].startswith("nd-")
    assert evidence["native_diagnostic_command"] == (
        f"yoke relay diagnostic {evidence['native_diagnostic_ref']}"
    )
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


def test_report_failure_keeps_local_diagnostic_ref_and_recipe(
    tmp_path: Path,
) -> None:
    job = {
        "job_kind": "wake",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
    }

    def dispatch(**kwargs):
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "jobs": [job]},
            )
        return SimpleNamespace(
            success=False,
            error=SimpleNamespace(code="control_plane_unreachable"),
        )

    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=lambda _job: RelayAdapterResult(
            "failed",
            private_diagnostic=RelayPrivateDiagnostic(
                "process_exit",
                error_step="session_lookup",
                stdout=b"private lookup stdout",
                stderr=b"private lookup stderr",
            ),
        ),
        clock=lambda: 1000.0,
    )

    assert outcome.state == "report_failed"
    assert outcome.jobs[0].error_code == "control_plane_unreachable"
    assert outcome.jobs[0].relay_id == f"machine:{MACHINE_ID}"
    assert outcome.jobs[0].machine_id == MACHINE_ID
    assert outcome.jobs[0].native_diagnostic_ref is not None
    assert outcome.jobs[0].native_diagnostic_command == (
        f"yoke relay diagnostic {outcome.jobs[0].native_diagnostic_ref}"
    )
    assert outcome.jobs[0].diagnostic_expires_at is not None
    assert "private lookup" not in repr(outcome)
    retained = read_native_diagnostic(
        outcome.jobs[0].native_diagnostic_ref,
        state_dir=tmp_path,
        now=1001,
    )
    assert b"private lookup stdout" in retained
    assert b"private lookup stderr" in retained


def test_storage_failure_reports_unavailable_without_raw_streams(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from yoke_harness.session_relay_native_diagnostics import NativeDiagnosticError

    def unavailable(*_args, **_kwargs):
        raise NativeDiagnosticError("private filesystem detail")

    monkeypatch.setattr(
        diagnostic_retention, "store_native_diagnostic", unavailable
    )
    result = diagnostic_retention.retain_private_diagnostic(
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


def test_storage_failure_keeps_typed_operator_outcome_and_location(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from yoke_harness.session_relay_native_diagnostics import NativeDiagnosticError

    job = {
        "job_kind": "wake",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
    }

    def unavailable(*_args, **_kwargs):
        raise NativeDiagnosticError("private filesystem detail")

    def dispatch(**kwargs):
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "jobs": [job]},
            )
        return SimpleNamespace(success=True, result={"state": "failed"})

    monkeypatch.setattr(
        diagnostic_retention, "store_native_diagnostic", unavailable
    )
    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=lambda _job: RelayAdapterResult(
            "failed",
            private_diagnostic=RelayPrivateDiagnostic(
                "process_exit",
                error_step="session_lookup",
                stderr=b"private native failure",
            ),
        ),
        clock=lambda: 1000.0,
    )

    assert outcome.state == "reported"
    assert outcome.jobs[0].diagnostic_availability == "unavailable"
    assert outcome.jobs[0].native_error_class == "process_exit"
    assert outcome.jobs[0].native_error_step == "session_lookup"
    assert outcome.jobs[0].machine_id == MACHINE_ID
    assert outcome.jobs[0].relay_id == f"machine:{MACHINE_ID}"
    assert outcome.jobs[0].native_diagnostic_ref is None
    assert "private native failure" not in repr(outcome)
    assert "private filesystem detail" not in repr(outcome)
