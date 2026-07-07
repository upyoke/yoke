"""Item-scoped stale-claim reclaim with shared activity recheck.

Owns ``reclaim_stale_item_claims`` — the surface session-offer's charge
dispatch reaches when it wants to clear stale exclusive claims on a
specific item before considering it for fresh acquisition.

The function uses the same canonical activity classifier as ``cmd_claim``
and ``clean_stale_harness_sessions`` (heartbeat plus latest tool-call
event), and runs a final recheck inside the same transaction immediately
before mutating each candidate row. When the recheck shows fresh
activity, the row is left untouched and ``ReclaimAborted`` is emitted
with ``scope='item_claim'``.

Lives in its own module so ``sessions_render_reclaim.py`` stays under
the 350-line authored-file limit (the full session-level reclaim flow
plus the item-scoped recheck would exceed the cap).
"""

from __future__ import annotations

from typing import Any

from . import db_backend
from . import sessions_analytics as _sa
from .session_reclaim_activity import (
    SCOPE_ITEM_CLAIM,
    classify_reclaimable,
)
from .sessions_analytics import (
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EVENT_RECLAIM_ABORTED,
    EVENT_WORK_RECLAIMED,
)
from .sessions_queries import _now_iso, normalize_claim_item_id
from .time_sql import now_sql


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def reclaim_stale_item_claims(
    conn: Any,
    item_id: str,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> int:
    """Release stale/ended exclusive item-target claims on ``item_id``.

    Item-scoped only — process and epic-task targets are not reclaimed
    through this surface.  Returns the number of claims released.
    """
    now = _now_iso()
    normalized = normalize_claim_item_id(item_id)
    if not normalized.isdigit():
        return 0
    item_id_int = int(normalized)

    p = _p(conn)
    _minutes_modifier = f"{p} || ' minutes'"
    candidate_rows = conn.execute(
        f"""SELECT wc.id, wc.session_id, wc.item_id, wc.task_num
           FROM work_claims wc
           LEFT JOIN harness_sessions ases ON ases.session_id = wc.session_id
           WHERE wc.target_kind='item' AND wc.item_id = {p}
             AND wc.released_at IS NULL
             AND wc.claim_type = 'exclusive'
             AND (
                 ases.ended_at IS NOT NULL
                 OR (wc.claimed_at)::timestamp < ({now_sql(offset_modifier=_minutes_modifier)})::timestamp
             )""",
        (item_id_int, f"-{stale_threshold_minutes}"),
    ).fetchall()

    released = 0
    for claim_row in candidate_rows:
        holder_session_id = claim_row["session_id"]
        recheck = classify_reclaimable(
            conn,
            holder_session_id,
            claim_id=claim_row["id"],
            base_ttl_minutes=stale_threshold_minutes,
        )
        if not recheck.is_reclaimable:
            evidence_payload = recheck.evidence.as_payload()
            _sa._emit_session_event(
                EVENT_RECLAIM_ABORTED,
                session_id=holder_session_id,
                item_id=(
                    str(claim_row["item_id"])
                    if claim_row["item_id"] is not None else None
                ),
                task_num=claim_row["task_num"],
                context={
                    "claim_id": claim_row["id"],
                    "scope": SCOPE_ITEM_CLAIM,
                    "original_session_id": holder_session_id,
                    "attempting_session_id": None,
                    "abort_reason": recheck.reason,
                    "executor": evidence_payload["executor"],
                    "effective_ttl_minutes": evidence_payload[
                        "effective_ttl_minutes"
                    ],
                    "original_session_last_heartbeat": evidence_payload[
                        "last_heartbeat"
                    ],
                    "original_session_last_event_at": evidence_payload[
                        "last_event_at"
                    ],
                    "reclaimed_by_item_offer": True,
                },
            )
            continue

        conn.execute(
            f"UPDATE work_claims SET released_at = {p}, release_reason = 'reclaimed' WHERE id = {p}",
            (now, claim_row["id"]),
        )
        released += 1

        _sa._emit_session_event(
            EVENT_WORK_RECLAIMED,
            session_id=holder_session_id,
            item_id=(
                str(claim_row["item_id"])
                if claim_row["item_id"] is not None else None
            ),
            task_num=claim_row["task_num"],
            context={
                "claim_id": claim_row["id"],
                "reason": "stale_item_claim_reclaimed",
                "reclaimed_by_item_offer": True,
            },
        )

    if released:
        conn.commit()

    return released


__all__ = ["reclaim_stale_item_claims"]
