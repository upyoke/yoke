"""Tell a released member's owner that this run cancelled its QA."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.db_optional_queries import rollback_savepoint
from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.deployment_run_membership_removals import membership_removals

_SEND_SAVEPOINT = "_yoke_removed_member_notice"


def notify_removed_member(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    public_ref: str,
    reason: str,
    removed_by: str,
) -> None:
    """Queue a notice with the removal, without risking its durable write.

    The caller commits. A send failure rolls back only this savepoint and
    names the manual recovery; it never reverses removal or grants a pass.
    """
    body = (
        f"{public_ref} was removed from run {run_id} by {removed_by}: {reason}. "
        "The outstanding run-bound QA was cancelled (not passed). "
        "The item rides a later release; do not attempt close-out or re-run "
        "merge close-out because this run succeeds. Keep the work claim and "
        f"re-park with `yoke sessions touch --mode parked --reason 'awaiting {public_ref} delivery'`."
    )
    try:
        conn.execute(f"SAVEPOINT {_SEND_SAVEPOINT}")
        project = query_one(
            conn, "SELECT project_id FROM items WHERE id=%s", (item_id,)
        )
        removal = next(
            entry
            for entry in membership_removals(conn, run_id)
            if int(entry["item_id"]) == int(item_id)
        )
        delivery = push_member_notice(
            conn,
            item_id=item_id,
            project_id=int(project["project_id"]),
            body_for_route=lambda _route: body,
            idempotency_key=f"removed-member:{run_id}:{item_id}:{removal['removed_at']}",
        )
    except Exception as exc:  # noqa: BLE001 - removal survives a notice failure
        rollback_savepoint(conn, _SEND_SAVEPOINT)
        print(
            f"member_removal_notice_failed: {public_ref} on {run_id}: {exc}. "
            f"Notify its holder manually: {body}",
            flush=True,
        )
        return
    conn.execute(f"RELEASE SAVEPOINT {_SEND_SAVEPOINT}")
    if not delivery:
        print(
            f"member_removal_notice_unaddressable: {public_ref} on {run_id}; "
            f"no holder or steering seat is addressable. Notify its owner manually: {body}",
            flush=True,
        )
