"""Stopped-session lifecycle assertions for Fleet live acceptance."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_wake_route import (
    MACHINE_SELECTED_ROUTE,
)
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_roster import (
    waiting_registration_ready,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)


def _cli_cell() -> AcceptanceCell:
    return AcceptanceCell(
        "codex-cli",
        "0.149.0-alpha.4",
        "identify",
        session_id="stopped-cli-session",
        wake_route="direct",
    )


def _desktop_cell(**overrides: Any) -> AcceptanceCell:
    values = {
        "surface": "claude-desktop",
        "expected_version": "1.34493.1",
        "mode": "identify",
        "session_id": "stopped-desktop-session",
        "acceptance_role": "surface",
        "wake_route": "none",
    }
    values.update(overrides)
    return AcceptanceCell(**values)


class _StopRaceClient(_ScenarioClient):
    def __init__(self, cell: AcceptanceCell) -> None:
        super().__init__(cell)
        self.target_reads = 0

    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        rows = result["rows"]
        if not rows or rows[0]["session_id"] != self.session_id:
            return result
        self.target_reads += 1
        if self.target_reads == 1:
            return result
        rows[0].update(
            {
                "liveness": "ended",
                "mode": "wait",
                "ended_at": "2026-08-23T12:00:00Z",
                "claims": [],
                "current_item": None,
                "turn_posture": ("unknown" if self.target_reads == 2 else "waiting"),
            }
        )
        return result


def test_driver_polls_stop_race_then_accepts_ended_waiting_cli() -> None:
    cell = _cli_cell()
    report = _driver(_StopRaceClient(cell))._run_cell(
        "yoke",
        cell,
        run_id="release-stop-race",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert report["status"] == "passed"
    assert report["stopped_liveness"] == "ended"
    assert report["stopped_session_mode"] == "wait"
    assert report["turn_posture"] == "waiting"


def _ended_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "liveness": "ended",
        "mode": "wait",
        "ended_at": "2026-08-23T12:00:00Z",
        "claims": [],
        "current_item": None,
        "turn_posture": "waiting",
    }
    row.update(overrides)
    return row


class _AckThenEndedDesktopClient(_ScenarioClient):
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
        self.ended_before_initial_ack = False

    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        initial_state = self.message_states.get("initial-message")
        initial_acknowledged = bool(initial_state and initial_state[0])
        for row in result["rows"]:
            if row["session_id"] != self.session_id:
                continue
            if not initial_acknowledged:
                self.ended_before_initial_ack |= row["liveness"] == "ended"
                continue
            row.update(_ended_row(**self.row_overrides))
            row["messageability"].update(
                {
                    "wake_interface": "none",
                    "wake_operation": "message_stopped",
                    "wake_available": False,
                    **self.routing_overrides,
                }
            )
        return result


def test_desktop_active_ack_then_ended_waiting_proves_no_wake() -> None:
    cell = _desktop_cell()
    client = _AckThenEndedDesktopClient(cell)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="release-desktop-active-ended",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert client.ended_before_initial_ack is False
    assert report["initial_message"]["state"] == "acknowledged"
    assert report["stopped_liveness"] == "ended"
    assert report["stopped_session_mode"] == "wait"
    assert report["turn_posture"] == "waiting"
    assert report["wake_outcome"] == "expected_unsupported"
    assert report["wake_message"]["native_wake"]["route"] == "none"


@pytest.mark.parametrize(
    ("cell", "row", "code"),
    (
        (
            AcceptanceCell(
                "codex-desktop",
                "26.818.31338",
                "identify",
                session_id="desktop-session",
            ),
            _ended_row(),
            "waiting_route_missing",
        ),
        (
            _desktop_cell(mode="create"),
            _ended_row(),
            "ended_waiting_cli_required",
        ),
        (
            _desktop_cell(wake_route="direct"),
            _ended_row(),
            "waiting_route_missing",
        ),
        (
            _desktop_cell(
                acceptance_role="broker",
                wake_route=MACHINE_SELECTED_ROUTE,
                broker_session_id="broker-session",
            ),
            _ended_row(),
            "waiting_route_missing",
        ),
        (
            _cli_cell(),
            _ended_row(claims=[{"target": "YOK-1"}]),
            "registration_claims_present",
        ),
        (_cli_cell(), _ended_row(current_item="YOK-1"), "registration_item_present"),
        (_cli_cell(), _ended_row(mode="charge"), "waiting_mode_drift"),
    ),
)
def test_ended_waiting_refuses_unsafe_terminal_shapes(
    cell: AcceptanceCell, row: dict[str, Any], code: str
) -> None:
    with pytest.raises(AcceptanceContractError) as failure:
        waiting_registration_ready(row, cell=cell, baseline_mode="wait")
    assert failure.value.code == code


@pytest.mark.parametrize("posture", ("unknown", "running"))
def test_ended_cli_posture_race_is_not_accepted(posture: str) -> None:
    assert not waiting_registration_ready(
        _ended_row(
            turn_posture=posture,
            messageability={
                "wake_interface": "supported",
                "wake_operation": "message_stopped",
                "wake_available": True,
            },
        ),
        cell=_cli_cell(),
        baseline_mode="wait",
    )


class _FastStopCreateClient(_ScenarioClient):
    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        for row in result["rows"]:
            if row["session_id"] == self.session_id:
                row.update(_ended_row())
        return result


def test_create_binding_accepts_fast_stopped_cli() -> None:
    cell = AcceptanceCell("codex-cli", "0.149.0-alpha.4", "create", wake_route="direct")
    report = _driver(_FastStopCreateClient(cell))._run_cell(
        "yoke",
        cell,
        run_id="release-fast-stop",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )
    assert report["status"] == "passed"
    assert report["stopped_liveness"] == "ended"


@pytest.mark.parametrize(
    ("routing_overrides", "code"),
    (
        ({"wake_operation": "message_idle"}, "waiting_route_missing"),
        ({"wake_available": True}, "waiting_wake_mismatch"),
        ({"wake_interface": "supported"}, "waiting_wake_interface_mismatch"),
    ),
)
def test_desktop_ended_waiting_refuses_wake_route_drift(
    routing_overrides: dict[str, Any], code: str
) -> None:
    cell = _desktop_cell()
    with pytest.raises(AcceptanceContractError) as failure:
        _driver(
            _AckThenEndedDesktopClient(cell, routing_overrides=routing_overrides)
        )._run_cell(
            "yoke",
            cell,
            run_id="release-desktop-ended-route-drift",
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
def test_desktop_ended_waiting_refuses_holdings(
    row_overrides: dict[str, Any], code: str
) -> None:
    cell = _desktop_cell()
    with pytest.raises(AcceptanceContractError) as failure:
        _driver(
            _AckThenEndedDesktopClient(cell, row_overrides=row_overrides)
        )._run_cell(
            "yoke",
            cell,
            run_id="release-desktop-ended-holdings",
            timeout=10,
            poll=1,
            unsupported_observation=2,
        )
    assert failure.value.code == code


class _UnsafeActiveClient(_ScenarioClient):
    def __init__(self, cell: AcceptanceCell, **overrides: Any) -> None:
        super().__init__(cell)
        self.overrides = overrides

    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        for row in result["rows"]:
            if row["session_id"] == self.session_id:
                row.update(self.overrides)
        return result


@pytest.mark.parametrize(
    ("overrides", "code"),
    (
        ({"claims": [{"target": "YOK-1"}]}, "registration_claims_present"),
        ({"current_item": "YOK-1"}, "registration_item_present"),
    ),
)
def test_active_waiting_refuses_holdings(overrides: dict[str, Any], code: str) -> None:
    cell = _cli_cell()
    with pytest.raises(AcceptanceContractError) as failure:
        _driver(_UnsafeActiveClient(cell, **overrides))._run_cell(
            "yoke",
            cell,
            run_id="release-active-holdings",
            timeout=10,
            poll=1,
            unsupported_observation=2,
        )
    assert failure.value.code == code
