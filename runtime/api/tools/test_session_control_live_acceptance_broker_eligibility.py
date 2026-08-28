"""Preview and registration consume one broker eligibility predicate."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    broker_session_eligibility,
)
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_roster import (
    validated_registration,
)
from runtime.api.tools.test_session_control_live_acceptance_broker import _broker_cell


def _row(session_id: str) -> dict[str, Any]:
    cell = _broker_cell()
    return {
        "session_id": session_id,
        "project": "yoke",
        "executor_surface": cell.surface,
        "executor_version": cell.expected_version,
        "machine_id": cell.machine_id,
        "mode": "wait",
        "claims": [],
        "current_item": None,
        "liveness": "active",
        "messageability": {"hook_injection": True},
    }


class _Client:
    def __init__(self, target: dict[str, Any], peer: dict[str, Any]) -> None:
        self.rows = {target["session_id"]: target, peer["session_id"]: peer}

    def call(self, args: list[str]) -> dict[str, Any]:
        session_id = args[args.index("--session") + 1]
        return {"rows": [self.rows[session_id]]}


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        ({"claims": [{"target": "YOK-2540"}]}, "registration_claims_present"),
        ({"executor_version": "0.0.1"}, "registration_version_mismatch"),
        ({"liveness": "unknown"}, "registration_not_active"),
    ),
)
def test_target_preview_and_registration_report_the_same_defect(
    changes: dict[str, Any], code: str
) -> None:
    cell = _broker_cell()
    target = _row(str(cell.session_id))
    target.update(changes)
    peer = _row(str(cell.broker_session_id))
    preview_code = broker_session_eligibility(
        target,
        project="yoke",
        surface=cell.surface,
        advertised_version=cell.expected_version,
        machine_id=str(cell.machine_id),
        role="target",
    )

    with pytest.raises(AcceptanceContractError) as failure:
        validated_registration(
            _Client(target, peer),
            project="yoke",
            cell=cell,
            session_id=str(cell.session_id),
        )

    assert preview_code == code
    assert failure.value.code == code


def test_claimed_peer_is_rejected_by_preview_and_registration() -> None:
    cell = _broker_cell()
    target = _row(str(cell.session_id))
    peer = _row(str(cell.broker_session_id))
    peer["claims"] = [{"target": "YOK-2473"}]
    preview_code = broker_session_eligibility(
        peer,
        project="yoke",
        surface=cell.surface,
        advertised_version=cell.expected_version,
        machine_id=str(cell.machine_id),
        role="peer",
    )

    with pytest.raises(AcceptanceContractError) as failure:
        validated_registration(
            _Client(target, peer),
            project="yoke",
            cell=cell,
            session_id=str(cell.session_id),
        )

    assert preview_code == "registration_claims_present"
    assert failure.value.code == preview_code


def test_ended_session_leftover_claims_do_not_disqualify() -> None:
    cell = _broker_cell()
    row = _row(str(cell.session_id))
    row.update(
        {
            "liveness": "ended",
            "terminated_at": None,
            "claims": [{"target": "YOK-2473"}],
        }
    )

    preview = broker_session_eligibility(
        row,
        project="yoke",
        surface=cell.surface,
        advertised_version=cell.expected_version,
        machine_id=str(cell.machine_id),
        role="target",
    )
    allowed = broker_session_eligibility(
        row,
        project="yoke",
        surface=cell.surface,
        advertised_version=cell.expected_version,
        machine_id=str(cell.machine_id),
        role="target",
        allow_ended=True,
    )

    assert preview == "registration_not_active"
    assert allowed is None
