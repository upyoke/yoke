# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import nullcontext

from runtime.api.fixtures.backlog import insert_item

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.actor_permissions import PERM_ITEMS_READ, PERM_ITEMS_WRITE

from yoke_core.domain import db_helpers

from yoke_core.domain.function_authz_scope import permission_key_for

from yoke_core.domain.handlers import (
    _register_item_worktrees,
    item_worktrees as handlers,
)

from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)

from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION

from yoke_core.domain.yoke_function_registry import RegistryEntry


def _request(
    function_id: str,
    *,
    item_id: int,
    payload: dict,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="item-worktree-handler-test"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )
