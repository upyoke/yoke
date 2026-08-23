"""Fail-closed roster validation for Fleet live acceptance."""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
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


def _validate_broker(
    rows: Any,
    *,
    project: str,
    cell: AcceptanceCell,
    target: dict[str, Any],
) -> None:
    if cell.route != "broker":
        return
    broker = _one_session(
        rows,
        session_id=str(cell.broker_session_id),
        surface=cell.surface,
        missing_code="broker_registration_missing",
    )
    if broker.get("project") != project:
        raise AcceptanceContractError("broker_project_mismatch", surface=cell.surface)
    if broker.get("machine_id") != target.get("machine_id"):
        raise AcceptanceContractError("broker_machine_mismatch", surface=cell.surface)
    if broker.get("liveness") != "active":
        raise AcceptanceContractError("broker_not_active", surface=cell.surface)
    routing = broker.get("messageability")
    if not isinstance(routing, dict) or routing.get("hook_injection") is not True:
        raise AcceptanceContractError("broker_hook_route_missing", surface=cell.surface)


def validated_registration(
    client: CommandClient,
    *,
    project: str,
    cell: AcceptanceCell,
    session_id: str,
) -> dict[str, Any]:
    result = client.call(["sessions", "list", "--project", project, "--limit", "500"])
    rows = result.get("rows")
    row = _one_session(
        rows,
        session_id=session_id,
        surface=cell.surface,
        missing_code="registration_missing",
    )
    checks = (
        ("project", project, "registration_project_mismatch"),
        ("executor_surface", cell.surface, "registration_surface_mismatch"),
        ("executor_version", cell.expected_version, "registration_version_mismatch"),
    )
    for field, expected, code in checks:
        if row.get(field) != expected:
            raise AcceptanceContractError(code, surface=cell.surface)
    if cell.machine_id and row.get("machine_id") != cell.machine_id:
        raise AcceptanceContractError(
            "registration_machine_mismatch", surface=cell.surface
        )
    if cell.model and row.get("model") != cell.model:
        raise AcceptanceContractError(
            "registration_model_mismatch", surface=cell.surface
        )
    if row.get("liveness") != "active":
        raise AcceptanceContractError("registration_not_active", surface=cell.surface)
    _validate_broker(rows, project=project, cell=cell, target=row)
    return row


__all__ = ["validated_registration"]
