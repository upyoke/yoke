"""Server-side reads and writes for project GitHub binding state.

Resolving a project's GitHub auth needs the binding rows, and stamping the
outcome of a GitHub call writes one of them back. Both run on whichever
machine drives the operation — and a merge, resync, or label sync driven from
a client whose control plane is https has no local Postgres to reach them
through. These handlers are the server-side half of that pair; the client
half in :mod:`yoke_core.domain.project_github_auth_state` and
:mod:`yoke_core.domain.project_github_sync_receipt` prefers a direct local
connection and relays here when there is none.

Nothing secret crosses this boundary. The binding and installation rows carry
repository metadata and granted permissions; the App private key and any
local user token are resolved by the caller from its own credential sources
after this state comes back.

``adapter_status='internal'`` — auth-resolution glue, never an agent CLI
surface, so these carry no CLI adapter inventory row.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class GithubStateReadRequest(BaseModel):
    """Payload for ``projects.github_state.read``."""

    project: str = Field(..., min_length=1)


class GithubStateReadResponse(BaseModel):
    project_slug: str
    project_id: Optional[int] = None
    has_capability: bool = False
    binding: Optional[Dict[str, Any]] = None
    installation: Optional[Dict[str, Any]] = None


class GithubSyncReceiptRequest(BaseModel):
    """Payload for ``projects.github_sync_receipt.record``."""

    project: str = Field(..., min_length=1)
    outcome: str = Field(..., pattern="^(success|failed)$")
    error: str = ""


class GithubSyncReceiptResponse(BaseModel):
    recorded: bool


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_github_state_read(request: FunctionCallRequest) -> HandlerOutcome:
    """Return one project's GitHub capability, binding, and installation."""
    from yoke_core.domain import project_github_auth_state as state_reader

    try:
        body = GithubStateReadRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"github state read payload invalid: {exc}")
    try:
        with _connect_rw() as conn:
            state = state_reader.read_github_state_over_connection(
                conn, body.project,
            )
    except Exception as exc:  # noqa: BLE001 - unresolvable auth blocks the caller
        return _err("github_state_read_failed", str(exc))
    return HandlerOutcome(
        result_payload=GithubStateReadResponse(
            **state_reader.state_payload(state)
        ).model_dump(),
        primary_success=True,
    )


def handle_github_sync_receipt(request: FunctionCallRequest) -> HandlerOutcome:
    """Stamp the terminal outcome of a project's GitHub automation."""
    from yoke_core.domain import project_github_sync_receipt as receipt

    try:
        body = GithubSyncReceiptRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"github sync receipt payload invalid: {exc}")
    try:
        with _connect_rw() as conn:
            recorded = receipt.record_over_connection(
                conn, body.project, outcome=body.outcome, error=body.error,
            )
    except Exception as exc:  # noqa: BLE001 - a lost receipt is reported, not raised
        return _err("github_sync_receipt_failed", str(exc))
    return HandlerOutcome(
        result_payload=GithubSyncReceiptResponse(recorded=recorded).model_dump(),
        primary_success=True,
    )


__all__ = [
    "GithubStateReadRequest",
    "GithubStateReadResponse",
    "GithubSyncReceiptRequest",
    "GithubSyncReceiptResponse",
    "handle_github_state_read",
    "handle_github_sync_receipt",
]
