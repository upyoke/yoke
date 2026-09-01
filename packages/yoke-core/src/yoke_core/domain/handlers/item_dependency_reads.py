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
                    "items.dependency.list requires target.kind='item' "
                    "with item_id"
                ),
            ),
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.item_dependency_read import dependency_rows

    item_id = int(target.item_id)
    conn = connect()
    try:
        rows = dependency_rows(conn, str(item_id))
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"item_id": item_id, "dependencies": rows},
        primary_success=True,
    )


__all__ = [
    "ItemDependencyListRequest",
    "ItemDependencyListResponse",
    "handle_item_dependency_list",
]
