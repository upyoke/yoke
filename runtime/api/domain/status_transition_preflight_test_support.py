# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from copy import deepcopy

from typing import Any

from runtime.api.fixtures.backlog import insert_item

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain import (
    backlog,
    backlog_update_op,
)

from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)

from yoke_core.domain.handlers.items_scalar import handle_scalar_update

from yoke_core.domain.handlers.lifecycle_transition import handle_transition

from yoke_core.domain.workflow_registry import publish_workflow_version

TARGET_STATUS = "refining-idea"


def _approval_definition(label: str, *, enabled: bool) -> dict[str, Any]:
    definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    definition["stages"][0]["label"] = label
    definition["policies"]["path_claims"] = "optional"
    definition["policies"]["approval_defaults"] = (
        {
            TARGET_STATUS: {
                "roles": ["owner"],
                "actors": [],
            },
        }
        if enabled
        else {}
    )
    return definition


def _publish_approval_workflow(
    conn: Any,
    *,
    label: str,
    enabled: bool,
) -> dict[str, Any]:
    return publish_workflow_version(
        conn,
        workflow_id="issue",
        definition=_approval_definition(label, enabled=enabled),
    )


def _actor_id(conn: Any) -> int:
    return int(
        conn.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )


def _request(
    *,
    item_id: int,
    actor_id: int,
    lifecycle: bool,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=(
            "lifecycle.transition.execute" if lifecycle else "items.scalar.update"
        ),
        actor=ActorContext(
            actor_id=str(actor_id),
            session_id=f"status-preflight-{item_id}",
        ),
        target=TargetRef(kind="item", item_id=item_id),
        payload=(
            {"target_status": TARGET_STATUS, "force": True}
            if lifecycle
            else {
                "field": "status",
                "value": TARGET_STATUS,
                "force": True,
            }
        ),
    )


def _isolate_status_effects(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_CLAIM_BYPASS", "test-isolation")
    monkeypatch.setattr(
        backlog_update_op,
        "run_post_db_sync",
        lambda **_kwargs: 0,
    )
