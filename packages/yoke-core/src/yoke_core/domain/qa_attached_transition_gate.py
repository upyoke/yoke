"""An attached transition owes its own QA, listed gate or not.

The status-write preflight materializes every plan case attached to the
target transition before any gate runs. A stage that lists
``qa_verification`` then checks every blocking verification requirement on
the item. A stage that does not list it — a polish entry, a Dash review
entry — would otherwise accept the transition with its own freshly
materialized cases unrun, deferring them to whichever later stage happens
to check. This gate closes that gap for exactly the requirements bound to
the transition being entered.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def evaluate(
    *, conn: Any, item_id: int, target_status: str, workflow: Any, **_: Any
) -> Optional[dict]:
    """Refuse while a blocking case bound to this transition has no pass."""
    from yoke_core.domain.qa_obligation_settlement import (
        item_supersession_open_sql,
        unretracted_requirement_sql,
    )
    from yoke_core.domain.qa_requirement_pass_currency import (
        has_current_passing_run,
    )
    from yoke_core.domain.qa_review_requests import requirement_awaits_human_review

    if GATE_QA_VERIFICATION in workflow.gate_ids_for_stage(target_status):
        return None
    if not _column_exists(conn, "qa_requirements", "workflow_transition_id"):
        return None
    marker = _p(conn)
    rows = query_rows(
        conn,
        "SELECT r.id, r.qa_kind FROM qa_requirements r "
        f"WHERE r.item_id = {marker} AND r.workflow_transition_id = {marker} "
        "AND r.blocking_mode = 'blocking' AND r.waived_at IS NULL "
        "AND r.qa_phase = 'verification' "
        f"AND {unretracted_requirement_sql(conn, 'r')} "
        f"AND {item_supersession_open_sql(conn, 'r')} ORDER BY r.id",
        (int(item_id), target_status),
    )
    open_rows = [
        row for row in rows if not has_current_passing_run(conn, int(row["id"]))
    ]
    if not open_rows:
        return None
    ref = render_item_ref(conn, int(item_id))
    lines = [
        f"Cannot advance {ref} to {target_status!r} — {len(open_rows)} blocking "
        "QA case(s) attached to this transition have no passing run."
    ]
    for row in open_rows:
        waiting = requirement_awaits_human_review(conn, int(row["id"]))
        lines.append(
            f"  - {waiting.detail} {waiting.recovery}"
            if waiting
            else f"  - Requirement #{row['id']} ({row['qa_kind']}): no passing run"
        )
    return {
        "success": False,
        "error_code": "GATE_QA_ATTACHED_TRANSITION",
        "error": "\n".join(lines),
        "remediation_hint": (
            f"Run the attached cases with `yoke qa plan run --item {ref} "
            f"--transition {target_status}`, then retry the transition."
        ),
    }


__all__ = ["evaluate"]
