"""Bounded contract rejection for durable relay reports."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_harness import session_relay
from yoke_harness.session_relay_health import (
    PENDING_REPORT_DIR_NAME,
    QUARANTINED_REPORT_DIR_NAME,
    RELAY_HEALTH_FILE_NAME,
    REPORT_ATTEMPT_DIR_NAME,
    observe_relay_health,
)
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_report_delivery import deliver_terminal_report
from yoke_harness.session_relay_report_retry import (
    quarantine_pending_report,
    retry_pending_reports,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _payload() -> dict[str, object]:
    return {
        "relay_id": f"machine:{MACHINE_ID}",
        "machine_id": MACHINE_ID,
        "job_kind": "launch",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
        "result": "outcome_unknown",
        "evidence": {"result_code": "native_exit", "body": "must not persist"},
    }


def _rejected() -> SimpleNamespace:
    return SimpleNamespace(
        success=False,
        error=SimpleNamespace(
            code="report_conflict",
            message="expired launch attempt already has another outcome",
        ),
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


def test_expired_launch_late_report_is_quarantined_and_heartbeat_continues(
    tmp_path: Path,
    caplog,
) -> None:
    claims = 0
    heartbeats = []

    def dispatch(**kwargs):
        nonlocal claims
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            claims += 1
            heartbeats.append(kwargs["payload"])
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "jobs": []},
            )
        return _rejected()

    deliver_terminal_report(
        dispatch,
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )
    first = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1000.0,
    )
    second = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1100.0,
    )

    # A permanently rejected report retries beside new work, never instead of it.
    assert first.state == "active"
    assert second.state == "active"
    assert claims == 2
    assert not list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))
    quarantine = tmp_path / QUARANTINED_REPORT_DIR_NAME
    payloads = [path for path in quarantine.glob("*.json") if ".meta." not in path.name]
    assert len(payloads) == 1
    assert "must not persist" not in payloads[0].read_text(encoding="utf-8")
    metadata = json.loads(next(quarantine.glob("*.meta.json")).read_text())
    assert metadata["error_code"] == "report_conflict"
    assert metadata["attempts"] == 3
    assert metadata["payload_sha256"] == sha256(payloads[0].read_bytes()).hexdigest()
    assert metadata["preserved_path"] == str(payloads[0])
    assert heartbeats[0]["health"]["state"] == "retrying"
    assert heartbeats[1]["health"]["state"] == "quarantined"
    assert "server_reason=report_conflict" in caplog.text
    assert "report " + metadata["report_id"] + " quarantined" in caplog.text
    assert observe_relay_health(tmp_path)["state"] == "quarantined"


@pytest.mark.parametrize("failure", ["transport", "server_error"])
def test_transient_failure_stays_in_the_retry_queue_and_holds_claims(
    tmp_path: Path, failure: str
) -> None:
    def transient(**kwargs):
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            pytest.fail("a report awaiting a transient retry holds new claims")
        if failure == "transport":
            raise OSError("transport unavailable")
        return SimpleNamespace(success=False, error=SimpleNamespace(code=failure))

    deliver_terminal_report(
        transient,
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )
    times = iter((1000.0, 1000.0, 1001.0, 1001.0, 1002.0, 1002.0, 1003.0, 1003.0))
    for _ in range(4):
        outcome = session_relay.serve_once(
            state_dir=tmp_path,
            inventory_provider=_inventory,
            dispatcher=transient,
            clock=lambda: next(times),
        )
        assert outcome.state == "report_failed"
        assert outcome.error_code == "relay_report_pending"

    assert len(list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))) == 1
    assert not (tmp_path / QUARANTINED_REPORT_DIR_NAME).exists()
    assert observe_relay_health(tmp_path)["state"] == "retrying"


@pytest.mark.parametrize(
    "code",
    ["relay_lease_expired", "invalid_state", "attempt_missing", "lease_mismatch"],
)
def test_never_acceptable_launch_report_is_quarantined_without_blocking_claims(
    tmp_path: Path, code: str
) -> None:
    claims = 0

    def dispatch(**kwargs):
        nonlocal claims
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            claims += 1
            return SimpleNamespace(
                success=True,
                result={"state": "active", "next_poll_seconds": 60, "jobs": []},
            )
        return SimpleNamespace(success=False, error=SimpleNamespace(code=code))

    deliver_terminal_report(
        dispatch,
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )
    attempts = tmp_path / REPORT_ATTEMPT_DIR_NAME
    assert [json.loads(p.read_text()) for p in attempts.glob("*.json")] == [
        {"attempts": 1, "error_code": code}
    ]
    for second in (1000.0, 1100.0):
        outcome = session_relay.serve_once(
            state_dir=tmp_path,
            inventory_provider=_inventory,
            dispatcher=dispatch,
            clock=lambda second=second: second,
        )
        assert outcome.state == "active"

    assert claims == 2
    health = observe_relay_health(tmp_path)
    assert health["pending_reports"] == 0
    assert health["quarantined_reports"][0]["error_code"] == code
    assert health["quarantined_reports"][0]["attempts"] == 3


def test_operator_quarantine_accepts_a_recorded_expired_lease_rejection(
    tmp_path: Path,
) -> None:
    deliver_terminal_report(
        lambda **kwargs: SimpleNamespace(
            success=False, error=SimpleNamespace(code="relay_lease_expired")
        ),
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )
    pending = next((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))

    metadata = quarantine_pending_report(pending.stem, state_dir=tmp_path)

    assert metadata["error_code"] == "relay_lease_expired"
    assert metadata["attempts"] == 1
    assert not pending.exists()
    assert observe_relay_health(tmp_path)["quarantine_count"] == 1


def test_permanently_rejected_evidence_is_logged_and_dropped(
    tmp_path: Path, caplog
) -> None:
    payload = {**_payload(), "job_kind": "evidence"}
    deliver_terminal_report(
        lambda **kwargs: _rejected(),
        session_relay.RELAY_REPORT_FUNCTION_ID,
        payload,
        state_dir=tmp_path,
        timeout_s=10,
    )
    health = observe_relay_health(tmp_path)
    assert health["state"] == "healthy"
    assert health["quarantine_count"] == 0
    assert health["pending_reports"] == 0
    assert not (tmp_path / RELAY_HEALTH_FILE_NAME).exists()
    assert caplog.text.count("relay_evidence_report_dropped") == 1
    assert "server_reason=report_conflict" in caplog.text
    assert retry_pending_reports(
        lambda **kwargs: pytest.fail("dropped evidence must not retry"),
        session_relay.RELAY_REPORT_FUNCTION_ID,
        state_dir=tmp_path,
        timeout_s=10,
    )
