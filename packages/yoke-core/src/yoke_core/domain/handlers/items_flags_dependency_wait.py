"""Refuse ``items.block`` when a live hard-block edge already carries the wait.

A dependency wait belongs on ``item_dependencies``: the evaluator reads
it live and the edge discharges itself. The blocked flag cannot. This
module names that refusal so ``items.block.run`` stays inside the
authored-file line cap.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.item_dependency import HARD_BLOCK_GATE_POINTS
from yoke_core.domain.schema_common import _table_exists


def refusal_for_dependency_wait(
    item_id: int, public_ref: str
) -> Optional[HandlerOutcome]:
    """Return a refusal when this item already has a live hard-block edge."""
    edges = _hard_block_edges(item_id)
    if not edges:
        return None
    named = "; ".join(
        f"{ref} ({gate_point}, {satisfaction})"
        for ref, gate_point, satisfaction in edges
    )
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code="dependency_wait_on_edge",
            message=(
                f"Cannot block {public_ref}: a live dependency edge already "
                f"carries this wait ({named}). Record a wait on another item "
                "with `yoke items dependency add` — an edge is evaluated live "
                "and discharges itself, a flag cannot."
            ),
        ),
    )


def _hard_block_edges(item_id: int) -> List[tuple[str, str, str]]:
    from yoke_core.domain import db_backend, db_helpers
    from yoke_core.domain.project_identity import render_item_ref

    with db_helpers.connect() as conn:
        if not _table_exists(conn, "item_dependencies"):
            return []
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        placeholders = ", ".join(marker for _ in HARD_BLOCK_GATE_POINTS)
        rows = conn.execute(
            "SELECT blocking_item_id, gate_point, satisfaction "
            f"FROM item_dependencies WHERE dependent_item_id = {marker} "
            f"AND gate_point IN ({placeholders}) "
            "ORDER BY blocking_item_id, gate_point",
            (int(item_id), *sorted(HARD_BLOCK_GATE_POINTS)),
        ).fetchall()
        named: List[tuple[str, str, str]] = []
        for row in rows:
            blocking_id = int(_cell(row, 0, "blocking_item_id"))
            named.append(
                (
                    render_item_ref(conn, blocking_id),
                    str(_cell(row, 1, "gate_point")),
                    str(_cell(row, 2, "satisfaction")),
                )
            )
        return named


def _cell(row: Any, index: int, name: str) -> Any:
    return row[name] if hasattr(row, "keys") else row[index]


__all__ = ["refusal_for_dependency_wait"]
