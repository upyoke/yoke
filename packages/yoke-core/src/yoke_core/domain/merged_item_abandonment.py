"""Durable resolution audit and live-run guard for merged abandonment."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.timestamps import iso8601_now


def abandonment_audit(
    conn: Any, *, item: dict, session_id: str | None, reason: str
) -> str:
    """Keep the resolution audit in the close transaction."""
    from yoke_core.domain.project_identity import placeholder

    _require_no_live_membership(conn, item_id=int(item["id"]))
    actor = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={placeholder(conn)}",
        (session_id,),
    ).fetchone()
    return json.dumps(
        {
            "action": "abandon_merged",
            "session_id": session_id,
            "actor_id": actor[0] if actor else None,
            "from_status": item["status"],
            "merged_at": str(item["merged_at"]),
            "reason": reason,
            "recorded_at": iso8601_now(),
        },
        sort_keys=True,
    )


def _require_no_live_membership(conn: Any, *, item_id: int) -> None:
    """The close caller holds the item binding lock, as membership writers do."""
    from yoke_contracts.refusal_recovery import compose_refusal

    from yoke_core.domain.project_identity import placeholder, render_item_ref
    from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
    from yoke_core.domain.sessions_analytics import SessionError

    rows = conn.execute(
        "SELECT dr.id, dr.status FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id=dr.id "
        f"WHERE dri.item_id={placeholder(conn)} ORDER BY dr.id",
        (item_id,),
    ).fetchall()
    live = [row for row in rows if row["status"] not in TERMINAL_RUN_STATUSES]
    if not live:
        return
    ref = render_item_ref(conn, item_id)
    runs = ", ".join(f"{row['id']} ({row['status']})" for row in live)
    commands = "; ".join(
        f"`yoke deployment-runs remove-item {row['id']} {ref} --reason TEXT`"
        for row in live
    )
    raise SessionError(
        "merged_item_live_deployment_run",
        compose_refusal(
            f"Cannot abandon {ref}: live deployment run membership: {runs}",
            recovery=(
                f"Remove the item first with {commands}, then retry abandonment. "
                "Removal is an audited operator act and obeys the run's removal "
                "gates; if removal is unavailable, finish or cancel the run first"
            ),
        ),
    )
