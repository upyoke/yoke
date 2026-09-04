"""Bounded contract rejection for durable relay reports."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_harness import session_relay
from yoke_harness.session_relay_health import (
    PENDING_REPORT_DIR_NAME,
    QUARANTINED_REPORT_DIR_NAME,
    observe_relay_health,
)
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_report_delivery import deliver_terminal_report


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _payload() -> dict[str, object]:
    return {
        "relay_id": f"machine:{MACHINE_ID}",
        "job_kind": "launch",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
        "result": "outcome_unknown",
        "evidence": {"result_code": "native_exit", "body": "must not persist"},
    }


def _rejected() -> SimpleNamespace:
    return SimpleNamespace(
        success=False,
        error=SimpleNamespace(code="payload_invalid"),
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


def test_rejected_report_is_quarantined_and_the_next_claim_proceeds(
    tmp_path: Path,
    caplog,
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
        clock=lambda: 1001.0,
    )

    assert first.state == "report_failed"
    assert second.state == "active"
    assert claims == 1
    assert not list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))
    quarantine = tmp_path / QUARANTINED_REPORT_DIR_NAME
    payloads = [path for path in quarantine.glob("*.json") if ".meta." not in path.name]
    assert len(payloads) == 1
    assert "must not persist" not in payloads[0].read_text(encoding="utf-8")
    metadata = json.loads(next(quarantine.glob("*.meta.json")).read_text())
    assert metadata["error_code"] == "payload_invalid"
    assert metadata["attempts"] == 3
    assert "server_reason=payload_invalid" in caplog.text
    assert "report " + metadata["report_id"] + " quarantined" in caplog.text
    assert observe_relay_health(tmp_path)["state"] == "quarantined"


def test_transport_failure_stays_in_the_retry_queue(tmp_path: Path) -> None:
    def offline(**_kwargs):
        raise OSError("transport unavailable")

    deliver_terminal_report(
        offline,
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
            dispatcher=offline,
            clock=lambda: next(times),
        )
        assert outcome.state == "report_failed"

    assert len(list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))) == 1
    assert not (tmp_path / QUARANTINED_REPORT_DIR_NAME).exists()
    assert observe_relay_health(tmp_path)["state"] == "retrying"
