"""Close a delivery-cleared member whose post-deploy work is satisfied.

The merge close-out is the one path to done. This module runs that same
close-out without a session when either the member recorded
``post_deploy_no_obligation`` or its completion-flow QA requirements all
passed or were discharged. An empty case set is still a member nobody asked
and stays held.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.dash_execution import evaluate_dash_evidence
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
from yoke_core.domain.gate_satisfier_resolution import record_delivery_evidence_rung
from yoke_core.domain.post_deploy_verification_answer import answer_for_item
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS
from yoke_core.domain.status_claim_bypass_context import status_bypass_override

CLAIM_BYPASS_PREFIX = "merge-close-out:"
STATUS_SOURCE = "merge-close-out"


@dataclass(frozen=True)
class DeliveryMemberCloseOut:
    """Whether this member can close without a wake, and the result.

    ``applies`` is the predicate the wake sites read: false means this is
    not an automatic-close case, so the ordinary delivery wake fires. True
    with ``ok=False`` tells the caller to send a recovery notice carrying
    ``detail``; a failed close-out must never strand the release-wait owner.
    """

    applies: bool
    ok: bool = False
    detail: str = ""


def recorded_no_obligation(conn: Any, item_id: int) -> bool:
    """The authored no-obligation fact, not a waiver and not silence."""
    return answer_for_item(conn, int(item_id)).no_obligation


def satisfied_delivery_member(conn: Any, *, item_id: int, run_id: str) -> bool:
    """Whether this run settled every scoped QA obligation for the member."""
    if recorded_no_obligation(conn, int(item_id)):
        return True
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return False
    total = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_requirements r "
        "WHERE r.deployment_run_id=%s AND r.deployment_member_item_id=%s "
        "AND r.qa_phase='post_deploy' AND r.blocking_mode='blocking'",
        (str(run_id), int(item_id)),
    )
    if not int(total or 0):
        return False
    unresolved = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_requirements r "
        "WHERE r.deployment_run_id=%s AND r.deployment_member_item_id=%s "
        "AND r.qa_phase='post_deploy' AND r.blocking_mode='blocking' "
        f"AND NOT {settled_obligation_sql(conn, 'r')} "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs qr "
        "WHERE qr.qa_requirement_id=r.id AND qr.verdict='pass')",
        (str(run_id), int(item_id)),
    )
    return int(unresolved or 0) == 0


def close_out_satisfied_delivery_member(
    conn: Any, *, item_id: int, public_ref: str, run_id: str, preview: bool = False
) -> DeliveryMemberCloseOut:
    """Run the merge close-out for one delivery-cleared satisfied member.

    Evidence must already be on the item from landing; this path never
    invents ``--result`` or ``--verification``. The status write is the
    same ``backlog.execute_update`` the merge close-out already uses,
    with a request-scoped claim bypass so it can run with no session.
    ``preview`` answers every gate of that write without making it, so a
    run can learn whether its members would close before it settles.
    """
    if not satisfied_delivery_member(conn, item_id=int(item_id), run_id=run_id):
        return DeliveryMemberCloseOut(applies=False)
    try:
        closed = _close_out(
            conn, item_id=int(item_id), public_ref=str(public_ref), preview=preview
        )
        if closed.ok and not preview:
            from yoke_core.domain.deployment_run_auto_completion import (
                continue_after_settlement,
            )

            continue_after_settlement(conn, run_id)
        return closed
    except Exception as exc:  # noqa: BLE001 - never reverse the succeeded run
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - the notice path reports its own failure
            pass
        return DeliveryMemberCloseOut(
            applies=True, ok=False, detail=str(exc) or exc.__class__.__name__
        )


def _close_out(
    conn: Any, *, item_id: int, public_ref: str, preview: bool = False
) -> DeliveryMemberCloseOut:
    from yoke_core.domain import backlog
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.standalone_item_merge import sync_item_to_github
    from yoke_core.domain.terminal_lane_cleanup import record_terminal_lane_close_out

    named = str(public_ref).strip() or render_item_ref(conn, item_id)
    status = _item_status(conn, item_id)
    if status == CLOSED_OUT_STATUS:
        return DeliveryMemberCloseOut(applies=True, ok=True, detail="already done")
    # The delivery this close-out answers is the canonical delivery rung's
    # evidence. Landing could not stamp it — the release was still pending —
    # so it is stamped here, before the evidence read that requires it,
    # rather than waking the holder to re-run a merge just to record it.
    record_delivery_evidence_rung(
        conn,
        item_id=item_id,
        merge_recorded=bool(item_merge_identity(conn, item_id)),
    )
    conn.commit()
    evidence = evaluate_dash_evidence(conn, item_id)
    if not evidence.satisfied:
        missing = ", ".join(evidence.missing) or "execution_evidence"
        return DeliveryMemberCloseOut(
            applies=True,
            ok=False,
            detail=(
                f"{named} has satisfied post-deploy delivery but cannot "
                f"auto-close: landing evidence is missing {missing}. Record "
                "it with `yoke merge item` `--result` and `--verification`, "
                "then re-drive the run."
            ),
        )
    captured = io.StringIO()
    with status_bypass_override(
        claim_bypass=f"{CLAIM_BYPASS_PREFIX}{named}",
        status_source=STATUS_SOURCE,
        task_done_verified=False,
    ):
        result = backlog.execute_update(
            item_id,
            "status",
            CLOSED_OUT_STATUS,
            session_id=None,
            out=captured,
            done_nonce_verified=True,
            expected_status=status,
            no_github=True,
            dry_run=preview,
        )
    if not result.get("success"):
        return DeliveryMemberCloseOut(
            applies=True,
            ok=False,
            detail=str(
                result.get("error") or captured.getvalue() or "close-out refused"
            ),
        )
    if preview:
        return DeliveryMemberCloseOut(applies=True, ok=True, detail="would close")
    github_error = sync_item_to_github(item_id)
    envelope: dict[str, Any] = {"warnings": []}
    if github_error:
        envelope["warnings"].append(f"GitHub sync skipped: {github_error}")
    record_terminal_lane_close_out(
        {"id": item_id, "public_ref": named, "claim": None},
        envelope,
        target_status=CLOSED_OUT_STATUS,
        landing_recorded=True,
    )
    _end_previous_claim_holders_if_empty(conn, item_id=item_id)
    print(f"{named}: post-deploy obligations satisfied; closed without a wake.")
    return DeliveryMemberCloseOut(applies=True, ok=True, detail="closed")


def _end_previous_claim_holders_if_empty(conn: Any, *, item_id: int) -> None:
    """End any previous holding sessions released by the transition if now empty."""
    from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty
    from yoke_core.domain.work_claim_targets import scope_int_sql

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_scope = scope_int_sql(conn, "scope", "item_id")
    epic_scope = scope_int_sql(conn, "scope", "epic_id")
    release_intent = f"item-terminal:{CLOSED_OUT_STATUS}"

    rows = conn.execute(
        "SELECT DISTINCT session_id FROM work_claims "
        f"WHERE release_reason_intent={marker} AND "
        f"((target_kind='item' AND {item_scope}={marker}) OR "
        f"(target_kind='epic_task' AND {epic_scope}={marker}))",
        (release_intent, int(item_id), int(item_id)),
    ).fetchall()

    session_ids = [
        str(row["session_id"] if hasattr(row, "keys") else row[0])
        for row in rows
        if row and (row["session_id"] if hasattr(row, "keys") else row[0])
    ]

    for session_id in sorted(set(session_ids)):
        try:
            end_session_if_empty(
                conn,
                session_id,
                triggered_by="delivery-satisfied-closeout",
            )
        except Exception:  # noqa: BLE001 - best-effort session cleanup
            pass


def _item_status(conn: Any, item_id: int) -> str:
    row = conn.execute(
        "SELECT status FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if row is None:
        return ""
    return str(row["status"] if hasattr(row, "keys") else row[0] or "")


__all__ = [
    "CLAIM_BYPASS_PREFIX",
    "STATUS_SOURCE",
    "DeliveryMemberCloseOut",
    "close_out_satisfied_delivery_member",
    "recorded_no_obligation",
    "satisfied_delivery_member",
]
