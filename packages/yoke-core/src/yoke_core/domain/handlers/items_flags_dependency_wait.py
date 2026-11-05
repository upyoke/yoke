"""Refuse ``items.block`` while an unsatisfied dependency carries the wait.

Dependency edges evaluate their satisfaction live and discharge the wait
when satisfied. A satisfied edge permits an unrelated blocked flag.
"""

from __future__ import annotations

from typing import List, Optional

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.schema_common import _table_exists


def refusal_for_dependency_wait(
    item_id: int, public_ref: str
) -> Optional[HandlerOutcome]:
    """Return a refusal only for unsatisfied hard-block dependencies."""
    edges = _hard_block_edges(item_id)
    if not edges:
        return None
    named = "; ".join(f"{ref} ({reason})" for ref, reason in edges)
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code="dependency_wait_on_edge",
            message=(
                f"Cannot block {public_ref}: unsatisfied dependency edges "
                f"already carry this wait ({named}). Wait for the blocking "
                "item, or remove the edge with `yoke items dependency remove`."
            ),
        ),
    )


def _hard_block_edges(item_id: int) -> List[tuple[str, str]]:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import render_item_ref

    with db_helpers.connect() as conn:
        if not _table_exists(conn, "item_dependencies"):
            return []
        return [
            (render_item_ref(conn, blocking_id), verdict.reason)
            for _, blocking_id, verdict in sorted(
                unsatisfied_dependency_pairs(conn, [item_id]),
                key=lambda pair: pair[1],
            )
        ]


__all__ = ["refusal_for_dependency_wait"]
