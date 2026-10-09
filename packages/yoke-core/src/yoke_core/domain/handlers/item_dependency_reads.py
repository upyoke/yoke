"""Item-dependency list handler: items.dependency.list.

Wraps :func:`yoke_core.domain.item_dependency_read.dependency_rows`
— the both-direction projection for ``item_dependencies`` rows.
``claim_required_kind=None`` (read).
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemDependencyListRequest(BaseModel):
    pass


class ItemDependencyListResponse(BaseModel):
    item_id: int
    dependencies: List[Dict[str, Any]]
    integration_gate: Dict[str, Any]


def handle_item_dependency_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message=(
                    "items.dependency.list requires target.kind='item' with public_ref"
                ),
            ),
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.dependency_planning import evaluate_item_gate
    from yoke_core.domain.item_dependency_read import dependency_rows
    from yoke_core.domain.project_identity import render_item_ref

    item_id = int(target.item_id)
    conn = connect()
    try:
        rows = dependency_rows(conn, item_id)
        try:
            public_ref = render_item_ref(conn, item_id, required=True)
            evaluation = evaluate_item_gate(conn, public_ref, "integration")
            integration_gate = {
                "evaluated": True,
                "is_blocked": evaluation.is_blocked,
                "blockers": [
                    {"public_ref": blocker.blocking_item, "reason": blocker.reason}
                    for blocker in evaluation.unsatisfied_blockers
                ],
            }
        except Exception:
            integration_gate = {
                "evaluated": False,
                "is_blocked": None,
                "error_code": "integration_dependency_evaluation_failed",
            }
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "dependencies": rows,
            "integration_gate": integration_gate,
        },
        primary_success=True,
    )


__all__ = [
    "ItemDependencyListRequest",
    "ItemDependencyListResponse",
    "handle_item_dependency_list",
]
