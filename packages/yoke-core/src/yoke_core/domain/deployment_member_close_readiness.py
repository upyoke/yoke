"""Ask whether one delivery-cleared member could close, without closing it.

Settlement closes members one at a time and each close-out commits on its
own, so a refusal reached part way through the loop used to leave some
members done and the rest at their release wait — a shared gate that passed
for everyone, applied to only some of them.

This module is the question that has to be answered before the first write:
run exactly the close-out the member would run, in the same claim-bypass
context, as a preview that rolls its status write back. Reusing the write
path's own ``dry_run`` is deliberate — a hand-rolled copy of the terminal
gates would drift away from the gates that actually refuse.
"""

from __future__ import annotations

import io
from typing import Any

from yoke_core.domain.no_obligation_member_close_out import (
    CLAIM_BYPASS_PREFIX,
    STATUS_SOURCE,
)
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS
from yoke_core.domain.status_claim_bypass_context import status_bypass_override


def _item_status(conn: Any, item_id: int) -> str:
    row = conn.execute(
        "SELECT status FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if row is None:
        return ""
    return str(row["status"] if hasattr(row, "keys") else row[0] or "")


def member_close_blocker(conn: Any, *, item_id: int, public_ref: str) -> str:
    """Why this member could not close now, or ``""`` when it could.

    An already-closed member reports no blocker: settlement replays over it
    rather than treating the second pass as a failure.
    """
    from yoke_core.domain import backlog
    from yoke_core.domain.dash_execution import evaluate_dash_evidence
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
    from yoke_core.domain.gate_satisfier_resolution import (
        record_delivery_evidence_rung,
    )

    named = str(public_ref)
    status = _item_status(conn, int(item_id))
    if status == CLOSED_OUT_STATUS:
        return ""
    # The same stamp the real close-out makes before reading evidence: the
    # delivery this settlement answers is the canonical delivery rung, and
    # landing could not record it while the release was still pending.
    record_delivery_evidence_rung(
        conn,
        item_id=int(item_id),
        merge_recorded=bool(item_merge_identity(conn, int(item_id))),
    )
    conn.commit()
    evidence = evaluate_dash_evidence(conn, int(item_id))
    if not evidence.satisfied:
        missing = ", ".join(evidence.missing) or "execution_evidence"
        return (
            f"landing evidence is missing {missing}. Record it with "
            "`yoke merge item` `--result` and `--verification`, then "
            "re-drive the run"
        )
    captured = io.StringIO()
    with status_bypass_override(
        claim_bypass=f"{CLAIM_BYPASS_PREFIX}{named}",
        status_source=STATUS_SOURCE,
        task_done_verified=False,
    ):
        result = backlog.execute_update(
            int(item_id),
            "status",
            CLOSED_OUT_STATUS,
            session_id=None,
            out=captured,
            done_nonce_verified=True,
            expected_status=status,
            no_github=True,
            dry_run=True,
        )
    if result.get("success"):
        return ""
    return str(result.get("error") or captured.getvalue() or "close-out refused")


__all__ = ["member_close_blocker"]
