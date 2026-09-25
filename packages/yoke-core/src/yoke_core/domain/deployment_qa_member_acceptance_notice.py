"""Close an independently delivered member or wake its release-wait owner.

The release-to-done gate already answers for one item, not the batch:
:func:`deployment_qa_run_acceptance.item_qa_acceptance_blockers` lists that
item's own item-scoped stages plus every run-scoped stage, and treats
another member's outstanding item-scoped QA as that member's problem. A
flow with no run QA can therefore close a final member when its own final
production QA passes. A flow with run QA still holds all members until the
shared QA and run success.

The satisfied path reuses the existing merge close-out. A refused close-out
uses the existing member wake with its reason and recovery. A failed send
is isolated so it cannot undo the acceptance that just committed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.db_optional_queries import rollback_savepoint
from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
)
from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.deployment_member_independent_close_out import (
    independent_member_delivery_ready,
)
from yoke_core.domain.merge_queue_landing_notice import HOLDER
from yoke_core.domain.release_wait_ownership import item_at_release_wait
from yoke_core.domain.schema_common import _table_exists
from yoke_contracts.public_ref import format_item_ref

#: One notice per item and the run whose item-scoped QA it accepted.
ITEM_QA_ACCEPTED_KEY_PREFIX = "release-wait-item-qa-accepted:"

_SEND_SAVEPOINT = "_yoke_item_qa_accepted_notice"


def item_qa_accepted_idempotency_key(item_id: int, run_id: str) -> str:
    """One notice per member and the run that accepted its item-scoped QA."""
    return f"{ITEM_QA_ACCEPTED_KEY_PREFIX}{item_id}:{run_id}"


def item_qa_accepted_message(
    *, public_ref: str, run_id: str, route: str, close_out_failure: str = ""
) -> str:
    """Name what was accepted and how the release-wait owner should wait."""
    lead = (
        f"{public_ref}'s item-scoped QA gate is clear on deployment run "
        f"{run_id}. The run may still be executing; the selected flow's "
        "shared QA decides whether sibling QA delays completion."
    )
    if close_out_failure:
        lead += f" Automatic close-out failed: {close_out_failure}."
    recovery = (
        "Automatic close-out needs recovery before this item can finish. "
        if close_out_failure
        else "The completion flow will auto-close this item when its remaining delivery and QA obligations clear. "
    )
    if route == HOLDER:
        return (
            f"{lead} You hold its work claim and parked on this wait, so this "
            f"is your re-entry. {recovery}Check the item; do not re-run merge solely for "
            f"this acceptance. If the item is still at release wait, re-park "
            f"with `yoke sessions touch "
            f'--mode parked --reason "awaiting {public_ref} delivery"`.'
        )
    return (
        f"{lead} Nobody holds its work claim. {recovery}Check `yoke deployment-runs get "
        f"{run_id}` for run status and recovery."
    )


def _release_wait_member(conn: Any, item_id: int) -> dict[str, Any] | None:
    """The parked member, or ``None`` when this item is not at its wait."""
    required = ("items", "projects", "workflow_versions")
    if not all(_table_exists(conn, name) for name in required):
        return None
    row = conn.execute(
        "SELECT i.id AS item_id,i.project_id,i.status,i.project_sequence,"
        "i.workflow_id,i.workflow_version_id,p.public_item_prefix,"
        "v.version,v.definition_json,v.definition_digest "
        "FROM items i "
        "JOIN projects p ON p.id=i.project_id "
        "JOIN workflow_versions v ON v.id=i.workflow_version_id "
        "WHERE i.id=%s",
        (int(item_id),),
    ).fetchone()
    if row is None or not item_at_release_wait(row, str(row["status"] or "")):
        return None
    return {
        "item_id": int(row["item_id"]),
        "project_id": int(row["project_id"]),
        "public_ref": format_item_ref(
            None, row["public_item_prefix"], row["project_sequence"]
        ),
    }


def _item_qa_cleared(conn: Any, *, run_id: str, item_id: int) -> bool:
    """Whether the gate's own per-item reader already lists nothing owed."""
    try:
        return not item_qa_acceptance_blockers(
            conn, run_id=str(run_id), item_id=int(item_id)
        )
    except Exception:  # noqa: BLE001 - an unreadable gate announces nothing
        return False


def notify_item_qa_accepted(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    now: Optional[datetime] = None,
) -> str:
    """Wake this member's release-wait owner when its own QA is accepted.

    ``""`` means nobody was owed one (not at the wait, still blocked, or
    nobody addressable). ``"undelivered"`` / ``"delivered"`` match
    :func:`push_member_notice`. A send failure is ``"failed: ..."`` and
    never reverses the acceptance.
    """
    if not run_id or not item_id:
        return ""
    from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
        withdraw_deployment_qa_wait_wakes,
    )

    withdraw_deployment_qa_wait_wakes(
        conn,
        run_id=str(run_id),
        item_id=int(item_id),
        reason="member_stage_credited",
        now=now,
    )
    if not _item_qa_cleared(conn, run_id=run_id, item_id=item_id):
        return ""
    member = _release_wait_member(conn, int(item_id))
    if member is None:
        return ""
    close_out_failure = ""
    if independent_member_delivery_ready(
        conn, item_id=int(item_id), run_id=str(run_id)
    ):
        from yoke_core.domain.no_obligation_member_close_out import (
            close_out_satisfied_delivery_member,
        )

        closed = close_out_satisfied_delivery_member(
            conn,
            item_id=int(item_id),
            public_ref=str(member["public_ref"]),
            run_id=str(run_id),
        )
        if closed.applies and closed.ok:
            return "closed"
        if closed.applies:
            close_out_failure = closed.detail
    stamp = now or datetime.now(timezone.utc)
    public_ref = str(member["public_ref"])
    try:
        conn.execute(f"SAVEPOINT {_SEND_SAVEPOINT}")
    except Exception as exc:  # noqa: BLE001 - reported, never reverses acceptance
        return f"failed: {exc}"
    try:
        delivery = push_member_notice(
            conn,
            item_id=int(member["item_id"]),
            project_id=int(member["project_id"]),
            body_for_route=lambda route, ref=public_ref: item_qa_accepted_message(
                public_ref=ref,
                run_id=str(run_id),
                route=route,
                close_out_failure=close_out_failure,
            ),
            idempotency_key=item_qa_accepted_idempotency_key(
                int(member["item_id"]), str(run_id)
            ),
            now=stamp,
        )
    except Exception as exc:  # noqa: BLE001 - reported, never reverses acceptance
        rollback_savepoint(conn, _SEND_SAVEPOINT)
        return f"failed: {exc}"
    try:
        conn.execute(f"RELEASE SAVEPOINT {_SEND_SAVEPOINT}")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - reported, never reverses acceptance
        return f"failed: {exc}"
    return delivery


__all__ = [
    "ITEM_QA_ACCEPTED_KEY_PREFIX",
    "item_qa_accepted_idempotency_key",
    "item_qa_accepted_message",
    "notify_item_qa_accepted",
]
