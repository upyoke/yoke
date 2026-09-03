"""Durable relay report delivery and launch-progress tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_harness import session_relay
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_report_delivery import (
    PENDING_REPORT_DIR_NAME,
    deliver_terminal_report,
    retry_pending_reports,
)
from yoke_harness.session_relay_runtime import RelayAdapterResult


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


def _job() -> dict[str, object]:
    return {
        "job_kind": "launch",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
        "surface": "claude-cli",
        "project_id": 10,
        "native_instruction": "opaque bootstrap",
        "launch_attestation": "secret-attestation",
    }


def _payload() -> dict[str, object]:
    return {
        "relay_id": f"machine:{MACHINE_ID}",
        "job_kind": "launch",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
        "result": "outcome_unknown",
        "native_id": None,
        "adapter_revision": "claude-native-v3",
        "evidence": {
            "result_code": "native_exit",
            "native_launch_phase": "adapter_complete",
            "stderr": "must not persist",
        },
    }


def test_failed_delivery_is_sanitized_on_disk_and_retried(tmp_path: Path) -> None:
    attempts = []

    def unavailable(**kwargs):
        attempts.append(kwargs)
        return SimpleNamespace(success=False)

    response = deliver_terminal_report(
        unavailable,
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )

    assert response.success is False
    pending = list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))
    assert len(pending) == 1
    on_disk = pending[0].read_text(encoding="utf-8")
    assert "must not persist" not in on_disk
    assert json.loads(on_disk)["evidence"] == {
        "native_launch_phase": "adapter_complete",
        "result_code": "native_exit",
    }

    delivered = retry_pending_reports(
        lambda **kwargs: attempts.append(kwargs) or SimpleNamespace(success=True),
        session_relay.RELAY_REPORT_FUNCTION_ID,
        state_dir=tmp_path,
        timeout_s=10,
    )

    assert delivered is True
    assert not list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))
    assert attempts[-1]["payload"]["result"] == "outcome_unknown"


def test_transport_exception_keeps_launch_report_for_the_next_poll(
    tmp_path: Path,
) -> None:
    def unavailable(**_kwargs):
        raise OSError("transport offline")

    response = deliver_terminal_report(
        unavailable,
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )

    assert isinstance(response, OSError)
    assert len(list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))) == 1


def test_every_launch_reports_start_and_terminal_phase_before_completion(
    tmp_path: Path,
) -> None:
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "jobs": [_job()]},
            )
        return SimpleNamespace(success=True, result={"state": "outcome_unknown"})

    def run(job):
        job["_launch_progress_reporter"](
            {
                "result_code": "native_spawn_pending",
                "native_launch_phase": "spawn_alive",
                "native_launch_pid": 4242,
            }
        )
        return RelayAdapterResult(
            "outcome_unknown",
            adapter_revision="claude-native-v3",
            evidence={"result_code": "native_exit", "surface": "claude-cli"},
        )

    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=run,
        clock=lambda: 1000.0,
    )

    assert outcome.state == "reported"
    reports = [call["payload"] for call in calls[1:]]
    assert [report["result"] for report in reports] == [
        "progress",
        "progress",
        "progress",
        "outcome_unknown",
    ]
    assert reports[0]["evidence"]["native_launch_phase"] == "adapter_start"
    assert reports[1]["evidence"]["native_launch_phase"] == "spawn_alive"
    assert reports[1]["evidence"]["native_launch_pid"] == 4242
    assert reports[2]["evidence"]["native_launch_phase"] == "adapter_complete"
    assert reports[3]["evidence"]["native_launch_phase"] == "adapter_complete"


def test_launch_registration_resolver_returns_the_server_candidate(
    tmp_path: Path,
) -> None:
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "jobs": [_job()]},
            )
        return SimpleNamespace(
            success=True,
            result={
                "job_kind": "launch",
                "result": {
                    "registration": {
                        "status": "registered_but_unbound",
                        "session_id": MACHINE_ID,
                    }
                },
            },
        )

    def run(job):
        registration = job["_launch_registration_resolver"]("/project")
        assert registration == {
            "status": "registered_but_unbound",
            "session_id": MACHINE_ID,
        }
        return RelayAdapterResult(
            "native_created",
            native_session_id=MACHINE_ID,
            evidence={"result_code": "registered_but_unbound"},
        )

    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=run,
        clock=lambda: 1000.0,
    )

    assert outcome.state == "reported"
    registration_call = next(
        call
        for call in calls
        if call.get("payload", {}).get("evidence", {}).get("result_code")
        == "identity_registration_wait"
    )
    assert registration_call["payload"]["evidence"]["native_launch_workspace"] == (
        "/project"
    )
    assert (
        registration_call["payload"]["evidence"]["native_launch_bound_seconds"] == 180
    )


def test_next_poll_drains_a_terminal_report_before_claiming_more_work(
    tmp_path: Path,
) -> None:
    terminal_attempts = 0
    claimed = 0

    def dispatch(**kwargs):
        nonlocal claimed, terminal_attempts
        payload = kwargs["payload"]
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            claimed += 1
            jobs = [_job()] if claimed == 1 else []
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "jobs": jobs},
            )
        if payload["result"] == "progress":
            return SimpleNamespace(success=True)
        terminal_attempts += 1
        return SimpleNamespace(success=terminal_attempts > 1)

    first = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=lambda _job: RelayAdapterResult(
            "outcome_unknown", evidence={"result_code": "native_exit"}
        ),
        clock=lambda: 1000.0,
    )
    second = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1001.0,
    )

    assert first.state == "report_failed"
    assert first.next_poll_seconds == 1
    assert second.state == "active"
    assert terminal_attempts == 2
    assert claimed == 2
