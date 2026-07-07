"""Backlog close operation — `execute_close` cancels an item through the
structured cancellation path: validates the resolution reason, refuses
to cancel items past review or with active worktrees, reconciles
`item_dependencies` rows, writes the status + resolution payload, and
posts the GitHub close + status comment.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, TextIO

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.backlog_queries import (
    _assert_write_db_ready,
    _normalize_item_ref,
    _resolve_write_db_path,
)
from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.path_claims_item_hook import (
    cancel_claims_on_item_terminal,
)


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def execute_close(
    item_id: int,
    reason: str,
    resolution_ref: Optional[str] = None,
    resolution_comment: Optional[str] = None,
    rebuild_board: bool = True,
    out: TextIO = sys.stdout,
) -> dict:
    """Close an item through the structured cancellation path."""
    allowed_reasons = {"duplicate", "wontfix", "obsolete", "out-of-scope"}
    if reason not in allowed_reasons:
        return {
            "success": False,
            "error": (
                " --reason must be one of: duplicate, wontfix, obsolete, "
                f"out-of-scope (got '{reason}')"
            ).lstrip(),
        }

    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)
    conn = connect(db_path)
    try:
        p = _p(conn)
        row = conn.execute(
            "SELECT i.*, p.slug AS project FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
        if row is None:
            return {"success": False, "error": f"Item YOK-{item_id} not found"}

        item = dict(row)
        status = item["status"]
        normalized_resolution_ref = _normalize_item_ref(resolution_ref)

        if status == "cancelled" and (item.get("resolution") or "") == reason:
            print(
                f"YOK-{item_id} already cancelled with resolution={reason} — no-op.",
                file=out,
            )
            return {"success": True, "item_id": item_id, "noop": True}

        if status == "done":
            return {
                "success": False,
                "error": f"YOK-{item_id} is already done — cannot close a delivered item.",
            }

        if status in {"reviewed-implementation", "polishing-implementation", "implemented", "release"}:
            return {
                "success": False,
                "error": (
                    f"YOK-{item_id} is in delivery tail (status={status}). "
                    "Cannot close items past review."
                ),
            }

        merged_at = item.get("merged_at")
        if merged_at not in (None, "", "null"):
            return {
                "success": False,
                "error": (
                    f"YOK-{item_id} has merged_at set ({merged_at}). "
                    "Cannot close items with merge evidence."
                ),
            }

        worktree = item.get("worktree")
        if worktree not in (None, "", "null"):
            return {
                "success": False,
                "error": (
                    f"YOK-{item_id} has an active worktree ({worktree}). "
                    "Remove the worktree first or use --force."
                ),
            }

        # reconcile item_dependencies before writing the cancel.
        # Outbound rows (where this item is the dependent) are always
        # removed — a cancelled item is no longer progressing through
        # gates. Inbound rows where resolution_ref names the dependent
        # are absorbed-self rows and can be safely removed. Other
        # inbound rows are preserved and reported as advisory warnings
        # so the operator can triage them with existing dependency
        # tooling. Deletion statements run on the same connection as
        # `_update_item_multi` below so the status change and
        # deterministic deletions commit atomically.
        sun_ref = f"YOK-{item_id}"
        outbound_rows = conn.execute(
            "SELECT blocking_item, gate_point, satisfaction "
            f"FROM item_dependencies WHERE dependent_item = {p}",
            (sun_ref,),
        ).fetchall()
        inbound_rows = conn.execute(
            "SELECT dependent_item, gate_point, satisfaction "
            f"FROM item_dependencies WHERE blocking_item = {p}",
            (sun_ref,),
        ).fetchall()

        removed_outbound: list[dict] = []
        for row in outbound_rows:
            removed_outbound.append(
                {
                    "blocking_item": row[0],
                    "gate_point": row[1],
                    "satisfaction": row[2],
                }
            )
        if outbound_rows:
            conn.execute(
                f"DELETE FROM item_dependencies WHERE dependent_item = {p}",
                (sun_ref,),
            )

        removed_absorbed: list[dict] = []
        preserved_ambiguous: list[dict] = []
        for row in inbound_rows:
            dependent_item = row[0]
            gate_point = row[1]
            satisfaction = row[2]
            if normalized_resolution_ref and dependent_item == normalized_resolution_ref:
                conn.execute(
                    "DELETE FROM item_dependencies "
                    f"WHERE dependent_item = {p} AND blocking_item = {p} "
                    f"AND gate_point = {p}",
                    (dependent_item, sun_ref, gate_point),
                )
                removed_absorbed.append(
                    {
                        "dependent_item": dependent_item,
                        "gate_point": gate_point,
                        "satisfaction": satisfaction,
                    }
                )
            else:
                preserved_ambiguous.append(
                    {
                        "dependent_item": dependent_item,
                        "blocking_item": sun_ref,
                        "gate_point": gate_point,
                        "satisfaction": satisfaction,
                    }
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
                "worktree": None,
                "resolution": reason,
                "resolution_ref": normalized_resolution_ref,
                "resolution_comment": resolution_comment,
            },
        )

        print(f"Updated: YOK-{item_id} status → cancelled (resolution: {reason})", file=out)

        # Audit-trail + claim-cleanup parity with the canonical writer in
        # backlog_update_op.execute_update. Without these, a status mutation
        # from execute_close leaves no ItemStatusChanged event and strands
        # any non-terminal path claims attached to the item.
        if old_status != "cancelled":
            from yoke_core.domain.item_status_transitions import (
                record_and_emit_item_status_change,
            )
            record_and_emit_item_status_change(
                conn,
                item_id=item_id,
                from_status=old_status,
                to_status="cancelled",
                source=os.environ.get("YOKE_STATUS_SOURCE", "execute-close"),
                out=out,
            )
        try:
            _n = cancel_claims_on_item_terminal(
                conn, item_id=item_id, new_status="cancelled"
            )
            if _n:
                print(
                    f"Cancelled {_n} non-terminal path claim(s) "
                    f"for YOK-{item_id}",
                    file=out,
                )
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        if removed_outbound:
            print(
                f"Reconciled: removed {len(removed_outbound)} outbound "
                f"dependency row(s) where YOK-{item_id} was the dependent_item.",
                file=out,
            )
        if removed_absorbed:
            print(
                f"Reconciled: removed {len(removed_absorbed)} absorbed-self "
                f"inbound row(s) where YOK-{item_id} blocked {normalized_resolution_ref}.",
                file=out,
            )
        if preserved_ambiguous:
            print(
                f"Warning: {len(preserved_ambiguous)} inbound dependency "
                f"row(s) preserved — cancelled YOK-{item_id} still listed as "
                "blocker. Review with `python3 -m yoke_core.cli.db_router "
                "shepherd dependency-list` and remove with "
                "`dependency-remove` if stale:",
                file=out,
            )
            for entry in preserved_ambiguous:
                print(
                    f"  - {entry['dependent_item']} <- {entry['blocking_item']}"
                    f" gate={entry['gate_point']}"
                    f" satisfaction={entry['satisfaction']}"
                    f" resolution={reason}"
                    f" resolution_ref={normalized_resolution_ref or ''}",
                    file=out,
                )
        # Lazy import: tests patch ``backlog_updates._is_dry_run``; looking
        # up the shim binding at call time preserves that contract.
        from yoke_core.domain import backlog_updates as _bu
        if _bu._is_dry_run():
            print(f"[DRY-RUN] Skipping GitHub: close + comment for YOK-{item_id}", file=out)
        else:
            _rendering._post_comment(item_id, old_status, "cancelled", out)
            _rendering._close_issue(item_id, out)

        _rendering._maybe_rebuild_board(rebuild_board, out=out)

        return {
            "success": True,
            "item_id": item_id,
            "dependency_reconciliation": {
                "outbound_removed": removed_outbound,
                "absorbed_inbound_removed": removed_absorbed,
                "preserved_ambiguous": preserved_ambiguous,
            },
        }
    finally:
        conn.close()


__all__ = ["execute_close"]
