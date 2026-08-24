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


_TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "cancelled", "expired", "outcome_unknown"}
)


def _launch_message_id(
    client: CommandClient,
    *,
    launch_id: str,
    session_id: str,
    surface: str,
) -> str:
    listed = client.call(
        [
            "messages",
            "list",
            "--recipient-session",
            session_id,
            "--limit",
            "500",
        ]
    )
    messages = listed.get("messages")
    if not isinstance(messages, list):
        raise AcceptanceContractError("launch_message_missing", surface=surface)
    matched: set[str] = set()
    expected = {"anchor": "launch", "launch_id": launch_id}
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = message.get("message_id")
        recipients = message.get("recipients")
        if not isinstance(message_id, str) or not message_id.strip():
            continue
        if not isinstance(recipients, list):
            continue
        if any(
            isinstance(recipient, dict)
            and recipient.get("session_id") == session_id
            and recipient.get("resolution_evidence") == expected
            for recipient in recipients
        ):
            matched.add(message_id.strip())
    if not matched:
        raise AcceptanceContractError("launch_message_missing", surface=surface)
    if len(matched) != 1:
        raise AcceptanceContractError("launch_message_ambiguous", surface=surface)
    return matched.pop()


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
        or selected.get("version") != cell.expected_version
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
    message_id = _launch_message_id(
        client,
        launch_id=launch_id,
        session_id=registered,
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


__all__ = ["create_and_bind"]
