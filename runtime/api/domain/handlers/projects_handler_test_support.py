"""Shared request and row builders for project handler tests."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def project_request(
    payload=None,
    function: str = "projects.get",
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def project_row(**overrides):
    row = {
        "id": 1,
        "slug": "demo",
        "name": "Demo",
        "emoji": None,
        "default_branch": "main",
        "github_repo": "owner/demo",
        "public_item_prefix": "DMO",
        "github_sync_mode": None,
        "created_at": "2026-01-01",
    }
    row.update(overrides)
    return row
