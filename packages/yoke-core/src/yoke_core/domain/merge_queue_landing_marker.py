"""The four ``items.merge_queue_*`` columns naming one item's landing.

They say which pull request an item lands through and how far that landing
has got: the pull request number, the queue admission, the landing, and the
notification. Writing them is one operation because they belong to one pull
request — repointing the number without dropping the stamps its predecessor
earned would attribute an old landing to a new carrier, which is the exact
confusion a repoint exists to fix.

Two callers write here. The merge boundary records the pull request it just
opened or armed. The operator correction repoints an item whose recorded
carrier never merged at the one that did. They share this writer so the
repoint can never be the weaker of the two.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain import db_backend
from yoke_core.domain.merge_queue_landing_record import delete_landing_record


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def read_landing_marker(conn: Any, item_id: int) -> Dict[str, str] | None:
    """The item's four landing facts, or ``None`` when the item is absent."""
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT merge_queue_pr_number, merge_queue_enqueued_at, "
        f"merge_queue_landed_at, merge_queue_notified_at FROM items WHERE id = {p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    return {
        "pr_number": str(row[0] or ""),
        "enqueued_at": str(row[1] or ""),
        "landed_at": str(row[2] or ""),
        "notified_at": str(row[3] or ""),
    }


def point_item_at_pull_request(
    conn: Any,
    item_id: int,
    pr_number: str,
    *,
    enqueued_at: str = "",
) -> Dict[str, str] | None:
    """Point the item at ``pr_number`` and return its four landing facts.

    Every landing stamp belongs to one pull request, so a number that
    supersedes the recorded one drops its predecessor's queue admission and
    landing stamps instead of carrying them onto the replacement, and the
    observation row goes with them. Re-writing the same number is
    idempotent: an admission already recorded survives a later caller that
    has none to declare. ``None`` when the item does not exist.
    """
    marker = read_landing_marker(conn, item_id)
    if marker is None:
        return None
    same_pr = marker["pr_number"] == pr_number
    recorded_enqueued_at = marker["enqueued_at"] if same_pr and marker["enqueued_at"] else enqueued_at
    landed_at = marker["landed_at"] if same_pr else ""
    notified_at = marker["notified_at"] if same_pr else ""
    reset_observation = not same_pr or bool(
        enqueued_at and not marker["enqueued_at"]
    )
    p = _placeholder(conn)
    conn.execute(
        "UPDATE items SET merge_queue_pr_number = {0}, "
        "merge_queue_enqueued_at = {0}, merge_queue_landed_at = {0}, "
        "merge_queue_notified_at = {0} WHERE id = {0}".format(p),
        (
            pr_number,
            recorded_enqueued_at or None,
            landed_at or None,
            notified_at or None,
            int(item_id),
        ),
    )
    if reset_observation:
        delete_landing_record(conn, int(item_id))
    conn.commit()
    return {
        "pr_number": pr_number,
        "enqueued_at": recorded_enqueued_at,
        "landed_at": landed_at,
        "notified_at": notified_at,
    }


__all__ = [
    "point_item_at_pull_request",
    "read_landing_marker",
]
