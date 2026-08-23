"""Stopped-session lifecycle assertions for Fleet live acceptance."""

from __future__ import annotations

from typing import Any

import pytest

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
            "ended_waiting_cli_required",
        ),
        (
            _cli_cell(),
            _ended_row(claims=[{"target": "YOK-1"}]),
            "ended_waiting_claims_present",
        ),
        (_cli_cell(), _ended_row(current_item="YOK-1"), "ended_waiting_item_present"),
        (_cli_cell(), _ended_row(mode="charge"), "ended_waiting_mode_invalid"),
    ),
)
def test_ended_waiting_refuses_unsafe_terminal_shapes(
    cell: AcceptanceCell, row: dict[str, Any], code: str
) -> None:
    with pytest.raises(AcceptanceContractError) as failure:
        waiting_registration_ready(row, cell=cell)
    assert failure.value.code == code


@pytest.mark.parametrize("posture", ("unknown", "running"))
def test_ended_cli_posture_race_is_not_accepted(posture: str) -> None:
    assert not waiting_registration_ready(
        _ended_row(turn_posture=posture), cell=_cli_cell()
    )
