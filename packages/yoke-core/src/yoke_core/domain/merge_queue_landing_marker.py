"""The four ``items.merge_queue_*`` columns naming one item's landing.

They say which pull request an item lands through and how far that landing
has got: the pull request number, the queue admission, the landing, and the
notification. Writing them is one operation because they belong to one pull
request — repointing the number without dropping the stamps its predecessor
earned would attribute an old landing to a new carrier, which is the exact
confusion a repoint exists to fix.

Three callers write here. The merge boundary records the pull request it just
opened or armed; for an item that already landed that becomes a re-land
attempt (:mod:`yoke_core.domain.merge_queue_landing_attempt`) and the columns
stay on the current landing. The landing observer promotes an attempt onto
the columns once GitHub reports it merged. The operator correction repoints
an item whose recorded carrier never merged at the one that did. They share
this module so the repoint can never be the weaker of the three.
"""

from __future__ import annotations

from typing import Any, Dict
from datetime import datetime

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter

from yoke_core.domain import db_backend
from yoke_core.domain.merge_queue_landing_attempt import (
    MERGED_REASON,
    close_attempt,
    close_open_attempts,
    item_has_landing,
    read_open_attempt,
    record_attempt,
    superseded_reason,
)
from yoke_core.domain.merge_queue_landing_record import delete_landing_record


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def read_landing_marker(
    conn: Any, item_id: int, *, for_pr_number: str | None = None
) -> Dict[str, Any] | None:
    """The item's four landing facts, or ``None`` when the item is absent."""
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT merge_queue_pr_number, merge_queue_enqueued_at, "
        f"merge_queue_landed_at, merge_queue_notified_at FROM items WHERE id = {p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    if for_pr_number is not None and str(row[0] or "") != for_pr_number:
        # Repointing drops the old carrier's stamps; none is clock evidence
        # for the replacement, even when historical storage is noncanonical.
        return dict(
            pr_number=str(row[0] or ""),
            enqueued_at=None,
            landed_at=None,
            notified_at=None,
        )
    return {
        "pr_number": str(row[0] or ""),
        "enqueued_at": parse_instant(row[1]) if row[1] not in (None, "") else None,
        "landed_at": parse_instant(row[2]) if row[2] not in (None, "") else None,
        "notified_at": parse_instant(row[3]) if row[3] not in (None, "") else None,
    }


def _write_columns(
    conn: Any,
    item_id: int,
    pr_number: str,
    enqueued_at: datetime | None,
    landed_at: datetime | None,
    notified_at: datetime | None,
) -> None:
    p = _placeholder(conn)
    conn.execute(
        "UPDATE items SET merge_queue_pr_number = {0}, "
        "merge_queue_enqueued_at = {0}, merge_queue_landed_at = {0}, "
        "merge_queue_notified_at = {0} WHERE id = {0}".format(p),
        (
            pr_number,
            instant_parameter(conn, enqueued_at),
            instant_parameter(conn, landed_at),
            instant_parameter(conn, notified_at),
            int(item_id),
        ),
    )


def repoint_item_at_pull_request(
    conn: Any,
    item_id: int,
    pr_number: str,
    *,
    enqueued_at: datetime | str | None = None,
) -> Dict[str, Any] | None:
    """Point the item's columns at ``pr_number`` and return its four landing facts.

    Every landing stamp belongs to one pull request, so a number that
    supersedes the recorded one drops its predecessor's queue admission and
    landing stamps instead of carrying them onto the replacement, and the
    observation row goes with them. Re-writing the same number is
    idempotent when it declares the same arming timestamp. A fresh timestamp
    replaces the stopped episode; a caller declaring none preserves it. An
    open re-land attempt for another pull request is closed as superseded.
    ``None`` when the item does not exist.
    """
    marker = read_landing_marker(conn, item_id, for_pr_number=pr_number)
    if marker is None:
        return None
    supplied = parse_instant(enqueued_at) if enqueued_at is not None else None
    same_pr = marker["pr_number"] == pr_number
    recorded_enqueued_at = (
        supplied
        if supplied is not None
        else (marker["enqueued_at"] if same_pr else None)
    )
    landed_at = marker["landed_at"] if same_pr else None
    notified_at = marker["notified_at"] if same_pr else None
    reset_observation = not same_pr or bool(
        supplied is not None and supplied != marker["enqueued_at"]
    )
    _write_columns(
        conn, item_id, pr_number, recorded_enqueued_at, landed_at, notified_at
    )
    if reset_observation:
        delete_landing_record(conn, int(item_id))
    close_open_attempts(conn, int(item_id), superseded_reason(pr_number))
    conn.commit()
    return {
        "pr_number": pr_number,
        "enqueued_at": recorded_enqueued_at,
        "landed_at": landed_at,
        "notified_at": notified_at,
    }


def point_item_at_pull_request(
    conn: Any,
    item_id: int,
    pr_number: str,
    *,
    enqueued_at: datetime | str | None = None,
) -> Dict[str, Any] | None:
    """Record ``pr_number`` as the item's landing pull request.

    The merge boundary's writer. An item that already landed keeps its
    current landing: a different pull request is recorded as a re-land
    attempt and returned with the same four facts, landing and notification
    empty. Otherwise the columns are repointed. ``None`` when the item does
    not exist.
    """
    marker = read_landing_marker(conn, item_id)
    if marker is None:
        return None
    if marker["pr_number"] != pr_number and (
        read_open_attempt(conn, item_id) is not None or item_has_landing(conn, item_id)
    ):
        supplied = parse_instant(enqueued_at) if enqueued_at is not None else None
        attempt, reset = record_attempt(
            conn, int(item_id), pr_number, enqueued_at=supplied
        )
        if reset:
            delete_landing_record(conn, int(item_id))
        conn.commit()
        return {
            "pr_number": pr_number,
            "enqueued_at": attempt["enqueued_at"],
            "landed_at": None,
            "notified_at": None,
        }
    return repoint_item_at_pull_request(
        conn, item_id, pr_number, enqueued_at=enqueued_at
    )


def promote_landing_attempt(conn: Any, item_id: int, pr_number: str) -> bool:
    """Make a merged attempt the item's current landing; the caller commits.

    The columns take the attempt's pull request and arming episode with no
    landing or notification yet, so the observer's own landing stamp and
    notice follow exactly as for a first landing. The observation row
    already describes this pull request and stays.
    """
    attempt = read_open_attempt(conn, item_id)
    if attempt is None or attempt["pr_number"] != pr_number:
        return False
    _write_columns(conn, item_id, pr_number, attempt["enqueued_at"], None, None)
    return close_attempt(conn, int(item_id), pr_number, MERGED_REASON)


__all__ = [
    "point_item_at_pull_request",
    "promote_landing_attempt",
    "read_landing_marker",
    "repoint_item_at_pull_request",
]
