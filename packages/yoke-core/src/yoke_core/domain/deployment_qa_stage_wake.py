"""Wake an item's claim holder when its scoped QA stage starts waiting.

RELEASES: "When the ordered flow reaches an item-scoped QA stage, the
existing yoke say messaging/wake system wakes each applicable item's
claiming session with the run, QA stage, configured deployed target and
revision." Reuses the landing-notice recipient/delivery primitives
(``merge_queue_landing_notice``) rather than a second wake pathway — the
run-scoped case (waking steering's assigned combined-review agent) is a
separate, not-yet-grounded mechanism and is out of scope here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.merge_queue_landing_notice import push_notice


def stage_wait_idempotency_key(run_id: str, stage_name: str, item_id: int) -> str:
    """One notice per run/stage/item, however many times the stage is checked."""
    return f"deployment-qa-stage-wait:{run_id}:{stage_name}:{item_id}"


def stage_wait_message(*, run_id: str, stage_name: str, reasons: str) -> str:
    """Name the run, stage, and exactly what is still outstanding."""
    return (
        f"Deployment run {run_id} reached item-scoped QA stage '{stage_name}' "
        f"and is waiting on your item's evidence/verdict: {reasons}"
    )


def notify_item_scoped_qa_wait(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    item_id: int,
    project_id: int,
    reasons: str,
    now: Optional[datetime] = None,
) -> str:
    """Wake the item's claim holder that its scoped QA stage is waiting.

    ``""`` means nobody was addressable, ``"undelivered"`` means queued but
    not yet reached, ``"delivered"`` means it reached the recipient —
    matching :func:`push_notice`'s own contract. The idempotency key is
    stable per (run, stage, item), so a stage rechecked on every pipeline
    retry sends exactly one notice per distinct wait, not one per check.
    """
    return push_notice(
        conn,
        item_id=item_id,
        project_id=project_id,
        body_for_route=lambda _route: stage_wait_message(
            run_id=run_id, stage_name=stage_name, reasons=reasons
        ),
        idempotency_key=stage_wait_idempotency_key(run_id, stage_name, item_id),
        now=now or datetime.now(timezone.utc),
    )


__all__ = [
    "notify_item_scoped_qa_wait",
    "stage_wait_idempotency_key",
    "stage_wait_message",
]
