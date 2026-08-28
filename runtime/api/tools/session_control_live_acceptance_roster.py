"""Fail-closed roster validation for Fleet live acceptance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    require_broker_session_eligibility,
)
from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_route_selection import (
    broker_hop_carries_wake,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    MACHINE_SELECTED_ROUTE,
)
from yoke_contracts.session_control.surface_versions import (
    surface_version_meets_floor,
)


def _one_session(
    rows: Any,
    *,
    session_id: str,
    surface: str,
    missing_code: str,
) -> dict[str, Any]:
    matches = (
        [
            row
            for row in rows
            if isinstance(row, dict) and row.get("session_id") == session_id
        ]
        if isinstance(rows, list)
        else []
    )
    if len(matches) != 1:
        raise AcceptanceContractError(missing_code, surface=surface)
    return matches[0]


def _read_session(
    client: CommandClient,
    *,
    project: str,
    session_id: str,
    surface: str,
    missing_code: str,
) -> dict[str, Any]:
    result = client.call(
        ["sessions", "list", "--project", project, "--session", session_id]
    )
    return _one_session(
        result.get("rows"),
        session_id=session_id,
        surface=surface,
        missing_code=missing_code,
    )


def _validate_broker(
    client: CommandClient,
    *,
    project: str,
    cell: AcceptanceCell,
    target: dict[str, Any],
) -> None:
    if cell.route != MACHINE_SELECTED_ROUTE:
        return
    broker = _read_session(
        client,
        project=project,
        session_id=str(cell.broker_session_id),
        surface=cell.surface,
        missing_code="broker_registration_missing",
    )
    require_broker_session_eligibility(
        broker,
        project=project,
        surface=cell.surface,
        advertised_version=cell.expected_version,
        machine_id=str(target.get("machine_id") or ""),
        role="peer",
        allow_ended=True,
    )
    if broker.get("liveness") == "active":
        return
    _validate_wakeable_ended_shape(broker, cell=cell)


def validated_registration(
    client: CommandClient,
    *,
    project: str,
    cell: AcceptanceCell,
    session_id: str,
    allow_ended: bool = False,
) -> dict[str, Any]:
    row = _read_session(
        client,
        project=project,
        session_id=session_id,
        surface=cell.surface,
        missing_code="registration_missing",
    )
    broker_cell = cell.acceptance_role == "broker"
    if broker_cell:
        require_broker_session_eligibility(
            row,
            project=project,
            surface=cell.surface,
            advertised_version=cell.expected_version,
            machine_id=str(cell.machine_id or ""),
            role="target",
            allow_ended=allow_ended,
        )
    else:
        checks = (
            ("project", project, "registration_project_mismatch"),
            ("executor_surface", cell.surface, "registration_surface_mismatch"),
        )
        for field, expected, code in checks:
            if row.get(field) != expected:
                raise AcceptanceContractError(code, surface=cell.surface)
        if not surface_version_meets_floor(
            cell.surface,
            str(row.get("executor_version") or ""),
            cell.expected_version,
        ):
            raise AcceptanceContractError(
                "registration_version_mismatch", surface=cell.surface
            )
        if cell.machine_id and row.get("machine_id") != cell.machine_id:
            raise AcceptanceContractError(
                "registration_machine_mismatch", surface=cell.surface
            )
    # Requested and registered model names use different harness vocabularies
    # (for example Cursor's native model versus its accepted CLI model), so the
    # launch binding records that difference rather than asserting equality.
    if not broker_cell:
        _validate_target_state(row, cell=cell)
    liveness = row.get("liveness")
    if liveness == "ended" and allow_ended:
        _validate_ended_registration(row, cell=cell)
    elif liveness != "active" and not broker_cell:
        raise AcceptanceContractError("registration_not_active", surface=cell.surface)
    _validate_broker(client, project=project, cell=cell, target=row)
    return row


def validated_stoppable_registration(
    client: CommandClient,
    project: str,
    cell: AcceptanceCell,
    session_id: str,
) -> dict[str, Any]:
    """Validate a launch registration that may already be waiting or ended."""
    return validated_registration(
        client,
        project=project,
        cell=cell,
        session_id=session_id,
        allow_ended=True,
    )


def registration_mode(row: dict[str, Any], *, cell: AcceptanceCell) -> str:
    value = row.get("mode")
    if not isinstance(value, str) or not value.strip():
        raise AcceptanceContractError("registration_mode_missing", surface=cell.surface)
    return value


def _validate_target_state(row: dict[str, Any], *, cell: AcceptanceCell) -> None:
    registration_mode(row, cell=cell)
    if "claims" not in row or row["claims"] != []:
        raise AcceptanceContractError(
            "registration_claims_present", surface=cell.surface
        )
    if "current_item" not in row or row["current_item"] is not None:
        raise AcceptanceContractError("registration_item_present", surface=cell.surface)


def _validate_ended_waiting_shape(row: dict[str, Any], *, cell: AcceptanceCell) -> None:
    desktop_active_proof = (
        cell.operation == "message_active"
        and cell.mode == "identify"
        and cell.acceptance_role == "surface"
        and cell.route == "none"
    )
    if not cell.surface.endswith("-cli") and not desktop_active_proof:
        raise AcceptanceContractError(
            "ended_waiting_cli_required", surface=cell.surface
        )
    if registration_mode(row, cell=cell) != "wait":
        raise AcceptanceContractError(
            "ended_waiting_mode_invalid", surface=cell.surface
        )
    if not row.get("ended_at"):
        raise AcceptanceContractError(
            "ended_waiting_stamp_missing", surface=cell.surface
        )


def wakeable_identify_baseline(cell: AcceptanceCell) -> bool:
    return cell.mode == "identify" and cell.route in {
        "direct",
        MACHINE_SELECTED_ROUTE,
    }


def _validate_wakeable_ended_shape(
    row: dict[str, Any], *, cell: AcceptanceCell
) -> None:
    if registration_mode(row, cell=cell) != "wait":
        raise AcceptanceContractError(
            "ended_waiting_mode_invalid", surface=cell.surface
        )
    if not row.get("ended_at"):
        raise AcceptanceContractError(
            "ended_waiting_stamp_missing", surface=cell.surface
        )
    routing = row.get("messageability")
    if (
        not isinstance(routing, dict)
        or routing.get("wake_operation") != "message_stopped"
    ):
        raise AcceptanceContractError("waiting_route_missing", surface=cell.surface)
    if routing.get("wake_interface") != "supported":
        raise AcceptanceContractError(
            "waiting_wake_interface_mismatch", surface=cell.surface
        )
    if routing.get("wake_available") is not True and not broker_hop_carries_wake(
        row, cell=cell
    ):
        raise AcceptanceContractError("waiting_wake_mismatch", surface=cell.surface)


def _validate_ended_registration(row: dict[str, Any], *, cell: AcceptanceCell) -> None:
    if wakeable_identify_baseline(cell):
        _validate_wakeable_ended_shape(row, cell=cell)
    else:
        _validate_ended_waiting_shape(row, cell=cell)


def waiting_registration_ready(
    row: dict[str, Any], *, cell: AcceptanceCell, baseline_mode: str
) -> bool:
    """Accept a route-specific Stop terminal shape after an active observation."""
    _validate_target_state(row, cell=cell)
    if registration_mode(row, cell=cell) != baseline_mode:
        raise AcceptanceContractError("waiting_mode_drift", surface=cell.surface)
    if row.get("liveness") == "active":
        return row.get("turn_posture") == "waiting"
    if row.get("liveness") != "ended":
        raise AcceptanceContractError("waiting_liveness_invalid", surface=cell.surface)
    _validate_ended_registration(row, cell=cell)
    return row.get("turn_posture") == "waiting"


def wait_for_waiting_registration(
    client: CommandClient,
    *,
    project: str,
    cell: AcceptanceCell,
    session_id: str,
    baseline_mode: str,
    timeout: float,
    poll: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    one_shot_private_wake_candidate: bool = False,
) -> dict[str, Any]:
    deadline = monotonic() + timeout
    while True:
        row = validated_stoppable_registration(client, project, cell, session_id)
        if waiting_registration_ready(row, cell=cell, baseline_mode=baseline_mode):
            routing = row.get("messageability")
            if (
                not isinstance(routing, dict)
                or routing.get("wake_operation") != "message_stopped"
            ):
                raise AcceptanceContractError(
                    "waiting_route_missing", surface=cell.surface
                )
            if (
                row.get("liveness") == "ended"
                and cell.route == "none"
                and routing.get("wake_interface") != "none"
            ):
                raise AcceptanceContractError(
                    "waiting_wake_interface_mismatch", surface=cell.surface
                )
            available = routing.get("wake_available") is True
            availability_relaxed = not available and (
                (one_shot_private_wake_candidate and cell.route == "direct")
                or broker_hop_carries_wake(row, cell=cell)
            )
            if available != (cell.route != "none") and not availability_relaxed:
                raise AcceptanceContractError(
                    "waiting_wake_mismatch", surface=cell.surface
                )
            return row
        if monotonic() >= deadline:
            raise AcceptanceContractError("waiting_timeout", surface=cell.surface)
        sleep(poll)


__all__ = [
    "registration_mode",
    "validated_registration",
    "validated_stoppable_registration",
    "wait_for_waiting_registration",
    "waiting_registration_ready",
    "wakeable_identify_baseline",
]
