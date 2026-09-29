"""Launch-and-bind evidence collection for Fleet live acceptance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    require_text,
)
from runtime.api.tools.session_control_live_acceptance_protocol import (
    initial_delivery_message,
)
from yoke_contracts.session_control.surface_versions import (
    surface_version_meets_floor,
)


_TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "cancelled", "expired", "outcome_unknown"}
)


def wait_for_registered_launch(
    client: CommandClient,
    *,
    launch: dict[str, Any],
    surface: str,
    timeout: float,
    poll: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> tuple[str, dict[str, Any]]:
    """Wait for native and registered identities before testing acknowledgement."""
    deadline = monotonic() + timeout
    current = launch
    while not current.get("registered_session_id"):
        if current.get("state") in _TERMINAL_STATES:
            raise AcceptanceContractError(
                "launch_registration_missing", surface=surface
            )
        if monotonic() >= deadline:
            raise AcceptanceContractError("launch_timeout", surface=surface)
        sleep(poll)
        launch_id = require_text(
            current.get("launch_id"), code="launch_id_missing", surface=surface
        )
        fetched = client.call(["session-control", "launch", "get", launch_id])
        current = fetched.get("launch")
        if not isinstance(current, dict):
            raise AcceptanceContractError("launch_evidence_missing", surface=surface)
    registered = require_text(
        current.get("registered_session_id"),
        code="launch_registration_missing",
        surface=surface,
    )
    if (
        current.get("requested_surface") != surface
        or current.get("native_session_id") != registered
        or current.get("state") not in {"awaiting_registration", "succeeded"}
    ):
        raise AcceptanceContractError("launch_identity_unproven", surface=surface)
    return registered, current


def create_and_bind(
    client: CommandClient,
    *,
    project: str,
    cell: AcceptanceCell,
    run_id: str,
    timeout: float,
    poll: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    validate_roster: Callable[[str, AcceptanceCell, str], dict[str, Any]],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """Create twice, then require registered and native identities to match."""
    selector = ["--project", project, "--surface", cell.surface]
    if cell.machine_id:
        selector.extend(["--machine", cell.machine_id])
    if cell.model:
        selector.extend(["--model", cell.model])
    preview = client.call(["sessions", "create", *selector, "--preview"])
    selected = preview.get("selected_relay")
    if (
        preview.get("launchable") is not True
        or not isinstance(selected, dict)
        or not surface_version_meets_floor(
            cell.surface,
            str(selected.get("version") or ""),
            cell.expected_version,
        )
    ):
        raise AcceptanceContractError(
            "launch_preview_unqualified", surface=cell.surface
        )
    instruction = initial_delivery_message(surface=cell.surface, phase="launch")
    args = [
        "sessions",
        "create",
        *selector,
        "--stdin",
        "--idempotency-key",
        f"fleet-live:{run_id}:{cell.surface}:launch",
    ]
    first = client.call(args, stdin=instruction)
    second = client.call(args, stdin=instruction)
    first_launch = first.get("launch")
    second_launch = second.get("launch")
    if not isinstance(first_launch, dict) or not isinstance(second_launch, dict):
        raise AcceptanceContractError("launch_evidence_missing", surface=cell.surface)
    launch_id = require_text(
        first_launch.get("launch_id"), code="launch_id_missing", surface=cell.surface
    )
    if (
        second_launch.get("launch_id") != launch_id
        or second.get("deduplicated") is not True
    ):
        raise AcceptanceContractError("launch_dedupe_failed", surface=cell.surface)
    registered, launch = wait_for_registered_launch(
        client,
        launch=first_launch,
        surface=cell.surface,
        timeout=timeout,
        poll=poll,
        sleep=sleep,
        monotonic=monotonic,
    )
    message_id = require_text(
        launch.get("message_id"),
        code="launch_message_missing",
        surface=cell.surface,
    )
    registration = validate_roster(project, cell, registered)
    return (
        registered,
        message_id,
        {
            "launch_id": launch_id,
            "deduplicated": bool(second.get("deduplicated")),
        },
        registration,
    )


__all__ = ["create_and_bind", "wait_for_registered_launch"]
