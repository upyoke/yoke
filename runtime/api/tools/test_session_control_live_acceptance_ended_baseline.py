"""Ended wakeable identify baselines for Fleet live acceptance."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)
from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction_sha256,
)


def _desktop_cell() -> AcceptanceCell:
    return AcceptanceCell(
        "claude-desktop",
        "1.34493.1",
        "identify",
        session_id="ended-desktop-session",
        acceptance_role="surface",
        wake_route="direct",
    )


class _EndedWakeableDesktopClient(_ScenarioClient):
    def __init__(
        self,
        cell: AcceptanceCell,
        *,
        row_overrides: dict[str, Any] | None = None,
        routing_overrides: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(cell)
        self.row_overrides = row_overrides or {}
        self.routing_overrides = routing_overrides or {}

    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        for row in result["rows"]:
            if row["session_id"] != self.session_id:
                continue
            row.update(
                {
                    "liveness": "ended",
                    "mode": "wait",
                    "ended_at": "2026-08-25T15:23:35Z",
                    "claims": [],
                    "current_item": None,
                    "turn_posture": "waiting",
                    **self.row_overrides,
                }
            )
            row["messageability"].update(
                {
                    "wake_interface": "supported",
                    "wake_operation": "message_stopped",
                    "wake_available": True,
                    **self.routing_overrides,
                }
            )
        return result

    def _send(self, argv: list[str]) -> dict[str, Any]:
        result = super()._send(argv)
        key = argv[argv.index("--idempotency-key") + 1]
        if key.endswith(":initial"):
            self.message_states["initial-message"] = (True, 1)
        return result

    def _message(self, message_id: str) -> dict[str, Any]:
        if message_id != "initial-message":
            return super()._message(message_id)
        self.message_states["wake-message"] = self.message_states[message_id]
        result = super()._message("wake-message")
        message = result["message"]
        message["message_id"] = message_id
        message["attempts"][0]["evidence"]["native_instruction_sha256"] = (
            native_wake_instruction_sha256(message_id)
        )
        return result


def test_ended_wakeable_desktop_baseline_proves_relay_wake_and_ack() -> None:
    cell = _desktop_cell()
    report = _driver(_EndedWakeableDesktopClient(cell))._run_cell(
        "yoke",
        cell,
        run_id="release-ended-desktop-baseline",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    initial_wake = report["initial_message"]["native_wake"]
    assert report["baseline_liveness"] == "ended"
    assert report["wake_supported"] is True
    assert initial_wake["attempt_kind"] == "wake_relay"
    assert initial_wake["native_traffic_body_free"] is True
    assert report["initial_message"]["injection_count"] == 1
    assert report["initial_message"]["wake_attempt_count"] == 1
    assert report["initial_message"]["state"] == "acknowledged"
    assert report["wake_message"]["state"] == "acknowledged"


@pytest.mark.parametrize(
    ("routing_overrides", "code"),
    (
        ({"wake_operation": "message_active"}, "waiting_route_missing"),
        ({"wake_interface": "none"}, "waiting_wake_interface_mismatch"),
        ({"wake_available": False}, "waiting_wake_mismatch"),
    ),
)
def test_ended_desktop_baseline_requires_a_live_stopped_wake_route(
    routing_overrides: dict[str, Any], code: str
) -> None:
    cell = _desktop_cell()
    with pytest.raises(AcceptanceContractError) as failure:
        _driver(
            _EndedWakeableDesktopClient(cell, routing_overrides=routing_overrides)
        )._run_cell(
            "yoke",
            cell,
            run_id="release-ended-desktop-route",
            timeout=10,
            poll=1,
            unsupported_observation=2,
        )
    assert failure.value.code == code


@pytest.mark.parametrize(
    ("row_overrides", "code"),
    (
        ({"claims": [{"target": "YOK-1"}]}, "registration_claims_present"),
        ({"current_item": "YOK-1"}, "registration_item_present"),
    ),
)
def test_ended_desktop_baseline_refuses_work_holdings(
    row_overrides: dict[str, Any], code: str
) -> None:
    cell = _desktop_cell()
    with pytest.raises(AcceptanceContractError) as failure:
        _driver(
            _EndedWakeableDesktopClient(cell, row_overrides=row_overrides)
        )._run_cell(
            "yoke",
            cell,
            run_id="release-ended-desktop-holdings",
            timeout=10,
            poll=1,
            unsupported_observation=2,
        )
    assert failure.value.code == code
