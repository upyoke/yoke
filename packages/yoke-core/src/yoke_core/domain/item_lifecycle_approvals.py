"""An item's work approvals, newest first, for its own detail page.

The same records a run card and the Inbox draw: each is a
:func:`~yoke_core.domain.decision_gate_record.gate_record`, so answering one
here answers the one decision everywhere, under the same authority. Withdrawn
requests were never decided and stay out; every pending or answered request
for any of the item's transitions is listed, each with its ``standing``
against the item as it is now.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain.decision_gate_record import gate_record
from yoke_core.domain.decision_request_contract import LIFECYCLE_TRANSITION_APPROVAL
from yoke_core.domain.decision_request_rows import request_rows
from yoke_core.domain.schema_common import _table_exists


def item_approval_gates(
    conn: Any, item_id: int, *, actor_id: Optional[int]
) -> list[dict[str, Any]]:
    """Every pending or answered work approval for *item_id*, newest first."""
    if not _table_exists(conn, "decision_requests"):
        return []
    ids = [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM decision_requests WHERE kind=%s "
            "AND subject_type='item_transition' AND subject_key LIKE %s "
            "AND status IN ('pending','resolved') ORDER BY id DESC",
            (LIFECYCLE_TRANSITION_APPROVAL, f"{int(item_id)}:%"),
        ).fetchall()
    ]
    composed = request_rows(conn, ids)
    return temporal_wire(
        [gate_record(conn, composed[request_id], actor_id=actor_id) for request_id in ids]
    )


__all__ = ["item_approval_gates"]
