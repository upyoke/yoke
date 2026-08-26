"""Ended target and peer baselines for the route-selection acceptance cell."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.test_session_control_live_acceptance_broker import _broker_cell
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)
from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction_sha256,
)


class _EndedBrokerClient(_ScenarioClient):
    def __init__(
        self,
        cell: AcceptanceCell,
        *,
        broker_overrides: dict[str, Any] | None = None,
        broker_routing_overrides: dict[str, Any] | None = None,
        machine_relay_fresh: bool = True,
    ) -> None:
        super().__init__(cell, machine_relay_fresh=machine_relay_fresh)
        self.broker_overrides = broker_overrides or {}
        self.broker_routing_overrides = broker_routing_overrides or {}

    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        for row in result["rows"]:
            overrides = (
                self.broker_overrides if row["session_id"] != self.session_id else {}
            )
            routing_overrides = (
                self.broker_routing_overrides
                if row["session_id"] != self.session_id
                else {}
            )
            row.update(
                {
                    "liveness": "ended",
                    "mode": "wait",
                    "ended_at": "2026-08-25T18:00:00Z",
                    "claims": [],
                    "current_item": None,
                    "turn_posture": "waiting",
                    **overrides,
                }
            )
            row["messageability"].update(
                {
                    "wake_interface": "supported",
                    "wake_operation": "message_stopped",
                    "wake_available": self.machine_relay_fresh,
                    "relay_connected": self.machine_relay_fresh,
                    **routing_overrides,
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


def test_ended_target_and_peer_are_valid_wakeable_baselines() -> None:
    """A relay-less machine keeps its ended baselines wakeable through the peer.

    Roster wake availability is derived from the machine relay the broker hop
    exists to replace, so the absent-relay branch must accept an unavailable
    machine route rather than refuse the baseline it is there to prove.
    """
    cell = _broker_cell()
    client = _EndedBrokerClient(cell, machine_relay_fresh=False)
    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="release-ended-broker",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert report["status"] == "passed"
    assert report["baseline_liveness"] == "ended"
    assert report["route_selection"]["selected_route"] == "broker"
    assert report["initial_message"]["native_wake"]["attempt_kind"] == "wake_broker"
    assert report["wake_message"]["native_wake"]["broker_session_id"] == (
        "broker-peer-session"
    )


@pytest.mark.parametrize(
    ("overrides", "routing_overrides", "code"),
    (
        ({"claims": [{"target": "held"}]}, {}, "registration_claims_present"),
        ({"current_item": "held"}, {}, "registration_item_present"),
        ({"mode": "charge"}, {}, "ended_waiting_mode_invalid"),
        ({"ended_at": None}, {}, "ended_waiting_stamp_missing"),
        ({}, {"wake_available": False}, "waiting_wake_mismatch"),
    ),
)
def test_ended_peer_requires_an_unclaimed_supported_waiting_shape(
    overrides: dict[str, Any],
    routing_overrides: dict[str, Any],
    code: str,
) -> None:
    with pytest.raises(AcceptanceContractError) as failure:
        _driver(
            _EndedBrokerClient(
                _broker_cell(),
                broker_overrides=overrides,
                broker_routing_overrides=routing_overrides,
            )
        )._run_cell(
            "yoke",
            _broker_cell(),
            run_id="release-unsafe-ended-broker",
            timeout=10,
            poll=1,
            unsupported_observation=2,
        )
    assert failure.value.code == code
