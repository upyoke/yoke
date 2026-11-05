"""Handler for ``items.github_sync``.

Bridges the backlog GitHub item sync into the registered function-call
surface while preserving the legacy allow-unclaimed ownership guard:
unclaimed items may sync, self-owned items may sync, and another live
session holding the item claim blocks the call.
"""

from __future__ import annotations

from yoke_core.domain.project_identity_item_ref import item_ref_for_id

from typing import Any, Dict, List
from shlex import quote

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    FunctionWarning,
    HandlerOutcome,
)
from yoke_core.domain import backlog_github_sync, db_helpers
from yoke_core.domain.backlog_github_sync_cli import check_ownership
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)


class GithubSyncRequest(BaseModel):
    """Payload for ``items.github_sync``."""


class GithubDoneSyncRequest(BaseModel):
    """Payload for ``items.github_done_sync``."""

    old_status: str = ""


class GithubSyncResponse(BaseModel):
    item_id: int
    exit_code: int
    skipped: bool = False


def _error_outcome(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _disabled_sync_outcome(item_id: int, operation: str) -> HandlerOutcome | None:
    with db_helpers.connect() as conn:
        context = backlog_github_sync._item_context(item_id, conn=conn)
        if context is None:
            return _error_outcome(
                "item_not_found",
                "Read the item reference and retry with an existing item.",
            )
        _, project, _repo = context
        if github_sync_enabled(project, conn=conn):
            return None
    return HandlerOutcome(
        result_payload=GithubSyncResponse(
            item_id=item_id,
            exit_code=0,
            skipped=True,
        ).model_dump(),
        primary_success=True,
        warnings=[
            FunctionWarning(
                code="github_sync_disabled",
                step="github_sync",
                detail=(
                    f"{github_sync_disabled_notice(project, operation)}. Enable with "
                    f"yoke projects update --slug {quote(project)} --name <Name> "
                    "--github-sync-mode enabled"
                ),
            )
        ],
    )


def handle_github_sync(request: FunctionCallRequest) -> HandlerOutcome:
    """Sync one backlog item or epic's tasks to GitHub."""
    if request.target.kind != "item" or request.target.item_id is None:
        return _error_outcome(
            "invalid_payload",
            "items.github_sync target must carry kind='item' + public_ref (PREFIX-N).",
        )
    try:
        GithubSyncRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error_outcome("invalid_payload", f"payload invalid: {exc}")

    item_id = int(request.target.item_id)
    allowed, _reason, holder = check_ownership(
        item_id,
        session_id=request.actor.session_id or None,
    )
    if not allowed:
        return _error_outcome(
            "claim_conflict",
            f"Refusing to sync item for {item_ref_for_id(item_id)}: "
            f"work claim held by session {holder}",
        )

    skipped = _disabled_sync_outcome(item_id, "sync-item")
    if skipped is not None:
        return skipped

    rc = backlog_github_sync.sync_item(item_id)
    if rc != 0:
        return _error_outcome(
            "github_sync_failed",
            f"GitHub sync failed for {item_ref_for_id(item_id)} with exit code {rc}.",
        )

    response = GithubSyncResponse(
        item_id=item_id,
        exit_code=rc,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


def handle_github_done_sync(request: FunctionCallRequest) -> HandlerOutcome:
    """Run the done-state GitHub closeout for one item.

    Registered so the done-transition engine can run this server-side. The
    closeout reads the item, renders its body, and stamps sync state, all of
    which need a control-plane connection — which the machine running the
    transition does not have when its control plane is reached over https.
    """
    if request.target.kind != "item" or request.target.item_id is None:
        return _error_outcome(
            "invalid_payload",
            "items.github_done_sync target must carry kind='item' + public_ref (PREFIX-N).",
        )
    try:
        payload = GithubDoneSyncRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error_outcome("invalid_payload", f"payload invalid: {exc}")

    item_id = int(request.target.item_id)
    allowed, _reason, holder = check_ownership(
        item_id,
        session_id=request.actor.session_id or None,
    )
    if not allowed:
        return _error_outcome(
            "claim_conflict",
            f"Refusing to sync item for {item_ref_for_id(item_id)}: "
            f"work claim held by session {holder}",
        )

    skipped = _disabled_sync_outcome(item_id, "done-sync")
    if skipped is not None:
        return skipped

    rc = backlog_github_sync.sync_done_item(item_id, payload.old_status)
    if rc != 0:
        return _error_outcome(
            "github_sync_failed",
            f"GitHub done sync failed for {item_ref_for_id(item_id)} "
            f"with exit code {rc}.",
        )

    response = GithubSyncResponse(
        item_id=item_id,
        exit_code=rc,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "items.github_done_sync",
        "handler": handle_github_done_sync,
        "request_model": GithubDoneSyncRequest,
        "response_model": GithubSyncResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_github_sync",
        "target_kinds": ["item"],
        "side_effects": ["github_sync"],
        "guardrails": [
            "allow_unclaimed_ownership_guard",
            "project_github_auth_required",
        ],
        # No CLI adapter: the done-transition engine is the only caller, and
        # it reaches this by relay when it has no local control plane. An
        # operator syncing an item by hand uses `yoke items github-sync`.
        "adapter_status": "internal",
        "claim_required_kind": None,
    },
    {
        "function_id": "items.github_sync",
        "handler": handle_github_sync,
        "request_model": GithubSyncRequest,
        "response_model": GithubSyncResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_github_sync",
        "target_kinds": ["item"],
        "side_effects": ["github_sync"],
        "guardrails": [
            "allow_unclaimed_ownership_guard",
            "project_github_auth_required",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "GithubDoneSyncRequest",
    "GithubSyncRequest",
    "GithubSyncResponse",
    "REGISTRATIONS",
    "handle_github_done_sync",
    "handle_github_sync",
]
