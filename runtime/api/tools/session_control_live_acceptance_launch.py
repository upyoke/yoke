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


_TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "cancelled", "expired", "outcome_unknown"}
)


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
) -> tuple[str, str, dict[str, Any]]:
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
        or selected.get("version") != cell.expected_version
    ):
        raise AcceptanceContractError(
            "launch_preview_unqualified", surface=cell.surface
        )
    instruction = (
        f"Fleet live acceptance launch for {cell.surface}. Acknowledge the "
        "injected launch message using its model-visible wrapper, then finish "
        "the top-level turn and wait. Do not delegate Fleet communication."
    )
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
    deadline = monotonic() + timeout
    launch = first_launch
    while launch.get("state") not in _TERMINAL_STATES:
        if monotonic() >= deadline:
            raise AcceptanceContractError("launch_timeout", surface=cell.surface)
        sleep(poll)
        fetched = client.call(["session-control", "launch", "get", launch_id])
        launch = fetched.get("launch")
        if not isinstance(launch, dict):
            raise AcceptanceContractError(
                "launch_evidence_missing", surface=cell.surface
            )
    registered = require_text(
        launch.get("registered_session_id"),
        code="launch_registration_missing",
        surface=cell.surface,
    )
    if (
        launch.get("state") != "succeeded"
        or launch.get("result_code") != "registered_and_injected"
        or launch.get("requested_surface") != cell.surface
        or launch.get("native_session_id") != registered
    ):
        raise AcceptanceContractError("launch_identity_unproven", surface=cell.surface)
    message_id = require_text(
        launch.get("message_id"), code="launch_message_missing", surface=cell.surface
    )
    validate_roster(project, cell, registered)
    return (
        registered,
        message_id,
        {
            "launch_id": launch_id,
            "deduplicated": bool(second.get("deduplicated")),
        },
    )


__all__ = ["create_and_bind"]
