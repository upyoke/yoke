"""The arming episode of an in-flight landing, on whichever record holds it.

A first landing keeps its episode in ``items.merge_queue_enqueued_at``; a
re-land attempt keeps it on its attempt record
(:mod:`yoke_core.domain.merge_queue_landing_attempt`). The observer restores
an episode it has evidence for and clears one whose stopped notice reached
its recipient. Both writes are compare-and-set against the candidate's pull
request, so a concurrent re-arm or repoint keeps its own episode.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.merge_queue_landing_attempt import write_attempt_episode


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def restore_episode(conn: Any, row: Mapping[str, Any], episode: datetime) -> bool:
    """Write ``episode`` where the candidate's episode is empty."""
    item_id, pr_number = int(row["id"]), str(row["merge_queue_pr_number"])
    if row.get("attempt"):
        return write_attempt_episode(
            conn, item_id, pr_number, value=episode, expected=None
        )
    p = _p(conn)
    cursor = conn.execute(
        f"UPDATE items SET merge_queue_enqueued_at={p} "
        f"WHERE id={p} AND merge_queue_pr_number={p} "
        "AND NULLIF(CAST(merge_queue_enqueued_at AS TEXT),'') IS NULL",
        (instant_parameter(conn, episode), item_id, pr_number),
    )
    return bool(cursor.rowcount)


def clear_episode(conn: Any, row: Mapping[str, Any], episode: datetime) -> None:
    """Clear the candidate's episode when it is still ``episode``."""
    item_id, pr_number = int(row["id"]), str(row["merge_queue_pr_number"])
    if row.get("attempt"):
        write_attempt_episode(conn, item_id, pr_number, value=None, expected=episode)
        return
    p = _p(conn)
    conn.execute(
        f"UPDATE items SET merge_queue_enqueued_at=NULL "
        f"WHERE id={p} AND merge_queue_pr_number={p} "
        f"AND merge_queue_enqueued_at={p}",
        (item_id, pr_number, instant_parameter(conn, episode)),
    )


__all__ = ["clear_episode", "restore_episode"]
