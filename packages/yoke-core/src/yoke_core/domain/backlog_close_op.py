"""Backlog close operation — `execute_close` cancels an item through the
structured cancellation path: validates the resolution reason, refuses
to cancel items past review unless an operator explicitly abandons merged
work with durable resolution audit, releases the item's own worktree lanes as
part of the same terminal close, removes every `item_dependencies` row
that names the item, tells each dependent's live holder,
writes the status + resolution payload, and posts the GitHub close +
status comment.
"""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.backlog_queries import (
    _assert_write_db_ready,
    _normalize_item_ref,
    _resolve_write_db_path,
)
from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.item_ref_columns import render_column_item_ref
from yoke_core.domain.project_identity import render_item_ref


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _notice_line(notice: dict) -> str:
    """One receipt line per dependent: who was told, or why nobody was."""
    dependent = notice["dependent_item"]
    delivery = notice["delivery"]
    if delivery == "no_live_holder":
        return f"Not notified: {dependent} has no live holder."
    if delivery == "cancelling_session":
        return f"Not notified: {dependent} is held by this session."
    return (
        f"Notified {dependent}'s holder session {notice['holder_session_id']} "
        f"({delivery})."
    )


def execute_close(
    item_id: int,
    reason: str,
    resolution_ref: Optional[str] = None,
    resolution_comment: Optional[str] = None,
    out: TextIO = sys.stdout,
    session_id: Optional[str] = None,
    abandon_merged: bool = False,
) -> dict:
    """Close an item through the structured cancellation path."""
    from yoke_core.domain.backlog_cancellation import normalize_cancellation_reason

    reason, reason_error = normalize_cancellation_reason(reason)
    if reason_error:
        return {"success": False, "error": reason_error}

    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)
    conn = connect(db_path)
    try:
        p = _p(conn)
        from yoke_core.domain.workflow_item_binding_lock import (
            lock_item_workflow_bindings,
        )

        lock_item_workflow_bindings(conn, (int(item_id),))
        # Best-effort public ref for every operator-facing message; falls
        # back to the default prefix form when the item cannot be resolved.
        public_ref = render_item_ref(conn, item_id)
        row = conn.execute(
            "SELECT i.*, p.slug AS project FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
        if row is None:
            return {"success": False, "error": f"Item {public_ref} not found"}

        item = dict(row)
        status = item["status"]
        merged = item.get("merged_at") not in (None, "", "null")
        if abandon_merged:
            from yoke_core.domain.merged_item_abandonment import abandonment_audit

            resolution_comment = abandonment_audit(
                conn, item=item, session_id=session_id, reason=reason
            )
            if not merged:
                return {
                    "success": False,
                    "error": "item_not_merged: use ordinary items cancel for unmerged work.",
                }
        normalized_resolution_ref = _normalize_item_ref(conn, resolution_ref)

        if status == "cancelled" and (item.get("resolution") or "") == reason:
            print(
                f"{public_ref} already cancelled with resolution={reason} — no-op.",
                file=out,
            )
            return {"success": True, "item_id": item_id, "noop": True}

        if status == "done":
            return {
                "success": False,
                "error": f"{public_ref} is already done — cannot close a delivered item.",
            }

        if not abandon_merged and status in {
            "reviewed-implementation",
            "polishing-implementation",
            "implemented",
            "release",
        }:
            return {
                "success": False,
                "error": (
                    f"{public_ref} is in delivery tail (status={status}). "
                    "Cannot close items past review."
                    " For merged work that cannot finish, an operator may use "
                    f"yoke items cancel {public_ref} --abandon-merged --reason TEXT."
                ),
            }

        merged_at = item.get("merged_at")
        if merged_at not in (None, "", "null") and not abandon_merged:
            return {
                "success": False,
                "error": (
                    f"{public_ref} has merged_at set ({merged_at}). "
                    "Cannot close items with merge evidence."
                    f" An operator may use yoke items cancel {public_ref} --abandon-merged "
                    "--reason TEXT when completion cannot be recovered."
                ),
            }

        # Reconcile item_dependencies before writing the cancel. A
        # cancelled item can neither progress through gates nor satisfy
        # one, so both its outbound rows (it is the dependent) and its
        # inbound rows (it is the blocker) are removed. The deletes run on
        # the same connection as `_update_item_multi` below so the status
        # change and the deletions commit atomically.
        outbound_rows = conn.execute(
            "SELECT blocking_item_id, gate_point, satisfaction "
            f"FROM item_dependencies WHERE dependent_item_id = {p}",
            (item_id,),
        ).fetchall()
        inbound_rows = conn.execute(
            "SELECT d.dependent_item_id, d.gate_point, d.satisfaction, "
            "i.project_id FROM item_dependencies d "
            "JOIN items i ON i.id = d.dependent_item_id "
            f"WHERE d.blocking_item_id = {p} "
            "ORDER BY d.dependent_item_id, d.gate_point",
            (item_id,),
        ).fetchall()
        removed_outbound = [
            {
                "blocking_item": render_column_item_ref(conn, row[0]),
                "gate_point": row[1],
                "satisfaction": row[2],
            }
            for row in outbound_rows
        ]
        removed_inbound = [
            {
                "dependent_item": render_column_item_ref(conn, row[0]),
                "gate_point": row[1],
                "satisfaction": row[2],
            }
            for row in inbound_rows
        ]
        dependents = list(
            {
                int(row[0]): (int(row[0]), entry["dependent_item"], int(row[3]))
                for row, entry in zip(inbound_rows, removed_inbound)
            }.values()
        )
        conn.execute(
            "DELETE FROM item_dependencies "
            f"WHERE dependent_item_id = {p} OR blocking_item_id = {p}",
            (item_id, item_id),
        )

        old_status = status
        # Lazy shim-routed lookup: tests patch
        # ``backlog_updates._update_item_multi`` to inject failures; looking
        # up the shim binding at call time preserves that contract.
        from yoke_core.domain import backlog_updates as _bu

        _bu._update_item_multi(
            conn,
            item_id,
            {
                "status": "cancelled",
                "frozen": 0,
                "resolution": reason,
                "resolution_ref": normalized_resolution_ref,
                "resolution_comment": resolution_comment,
            },
            commit=False,
        )
        from yoke_core.domain.backlog_update_effects import (
            run_post_commit_update_effects,
            run_transactional_update_effects,
        )

        effect_receipt = run_transactional_update_effects(
            conn,
            item_id=item_id,
            field="status",
            value="cancelled",
            old_status=old_status,
            session_id=session_id,
            out=out,
            status_source="abandon-merged" if abandon_merged else "execute-close",
        )
        conn.commit()

        print(
            f"Updated: {public_ref} status → cancelled (resolution: {reason})",
            file=out,
        )
        run_post_commit_update_effects(
            conn,
            receipt=effect_receipt,
            out=out,
        )
        from yoke_core.domain.backlog_cancel_dependent_notice import (
            notify_after_cancel,
        )

        holder_notices, notice_advisory = notify_after_cancel(
            conn,
            blocker_id=item_id,
            blocker_ref=public_ref,
            reason=reason,
            replacement_ref=normalized_resolution_ref,
            dependents=dependents,
            canceller_session_id=session_id,
        )
        if removed_outbound:
            print(
                f"Reconciled: removed {len(removed_outbound)} dependency "
                f"row(s) where {public_ref} was the dependent.",
                file=out,
            )
        if removed_inbound:
            print(
                f"Reconciled: removed {len(removed_inbound)} dependency "
                f"row(s) where {public_ref} was the blocker:",
                file=out,
            )
            for entry in removed_inbound:
                print(
                    f"  - {entry['dependent_item']} gate={entry['gate_point']}"
                    f" satisfaction={entry['satisfaction']}",
                    file=out,
                )
        for notice in holder_notices:
            print(_notice_line(notice), file=out)
        if notice_advisory:
            print(f"Warning: {notice_advisory}", file=out)
        # Lazy import: tests patch ``backlog_updates._is_dry_run``; looking
        # up the shim binding at call time preserves that contract.
        from yoke_core.domain import backlog_updates as _bu

        if _bu._is_dry_run():
            print(
                f"[DRY-RUN] Skipping GitHub: close + comment for {public_ref}",
                file=out,
            )
        else:
            _rendering._post_comment(item_id, old_status, "cancelled", out)
            _rendering._close_issue(item_id, out)

        return {
            "success": True,
            "item_id": item_id,
            "dependency_reconciliation": {
                "outbound_removed": removed_outbound,
                "inbound_removed": removed_inbound,
                "holder_notices": holder_notices,
                "notice_advisory": notice_advisory,
            },
        }
    finally:
        conn.close()


__all__ = ["execute_close"]
