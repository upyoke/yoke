"""Handler for ``items.github_sync``.

Bridges the backlog GitHub item sync into the registered function-call
surface while preserving the legacy allow-unclaimed ownership guard:
unclaimed items may sync, self-owned items may sync, and another live
session holding the item claim blocks the call.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import backlog, backlog_github_sync
from yoke_core.domain.backlog_github_sync_cli import check_ownership


class GithubSyncRequest(BaseModel):
    """Payload for ``items.github_sync``."""


class GithubSyncResponse(BaseModel):
    item_id: int
    exit_code: int
    board_rebuild_requested: bool


def _error_outcome(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_github_sync(request: FunctionCallRequest) -> HandlerOutcome:
    """Sync one backlog item or epic's tasks to GitHub."""
    if request.target.kind != "item" or request.target.item_id is None:
        return _error_outcome(
            "invalid_payload",
            "items.github_sync target must carry kind='item' + item_id.",
        )
    try:
        GithubSyncRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error_outcome("invalid_payload", f"payload invalid: {exc}")

    item_id = int(request.target.item_id)
    item_ref = str(item_id)
    allowed, _reason, holder = check_ownership(
        item_ref,
        session_id=request.actor.session_id or None,
    )
    if not allowed:
        return _error_outcome(
            "claim_conflict",
            f"Refusing to sync item for {item_ref}: "
            f"work claim held by session {holder}",
        )

    rc = backlog_github_sync.sync_item(item_ref)
    if rc != 0:
        return _error_outcome(
            "github_sync_failed",
            f"GitHub sync failed for YOK-{item_id} with exit code {rc}.",
        )

    backlog._maybe_rebuild_board(True)
    response = GithubSyncResponse(
        item_id=item_id,
        exit_code=rc,
        board_rebuild_requested=True,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "items.github_sync",
        "handler": handle_github_sync,
        "request_model": GithubSyncRequest,
        "response_model": GithubSyncResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_github_sync",
        "target_kinds": ["item"],
        "side_effects": ["github_sync", "rebuild_board"],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [
            "allow_unclaimed_ownership_guard",
            "project_github_auth_required",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "GithubSyncRequest",
    "GithubSyncResponse",
    "REGISTRATIONS",
    "handle_github_sync",
]
