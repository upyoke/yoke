"""Refuse a materialize that would leave a replaced case's row standing.

Materialize only adds rows, so a live item row whose case left the plan would
stand beside its replacement and keep owing proof. Rematerialize is the path
that retires it: superseded by its one successor, or waived as removed.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.qa_plan_case_currency import ORPHANED, _divergence_for_row
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.qa_plan_management import QaPlanError


def require_no_orphaned_item_rows(
    conn: Any, *, item_id: int, transition_id: str, plan_ids: list[int]
) -> None:
    """Name every live orphaned row and the rematerialize that retires them."""
    if not plan_ids:
        return
    m = marker(conn)
    rows = query_rows(
        conn,
        f"SELECT * FROM qa_requirements WHERE item_id={m} "
        f"AND workflow_transition_id={m} AND deployment_run_id IS NULL "
        f"AND plan_id IN ({','.join(m for _ in plan_ids)}) ORDER BY id",
        (int(item_id), str(transition_id), *map(int, plan_ids)),
    )
    found = (
        _divergence_for_row(conn, row)
        for row in rows
        if not obligation_settled(dict(row))
    )
    orphaned = [d for d in found if d is not None and d.state == ORPHANED]
    if orphaned:
        raise QaPlanError(
            "qa_plan_rows_orphaned: live QA requirement(s) "
            f"{', '.join(str(d.requirement_id) for d in orphaned)} stand for "
            "case(s) their plan no longer carries; materialize only adds rows, "
            "so they would keep owing proof beside their replacements. Nothing "
            "was written. Rematerialize retires them (a replaced post_deploy "
            "row is superseded by its successor, a removed one is waived): "
            f"{orphaned[0].refresh_command}"
        )


__all__ = ["require_no_orphaned_item_rows"]
