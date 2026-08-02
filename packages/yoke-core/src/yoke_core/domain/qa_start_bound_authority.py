"""Recording authority a QA gate run pins when it starts.

``qa.case_execution.begin`` is the doorman for one materialized case, and
the dispatcher verifies there that the calling session holds the subject
item's work claim. That verification is the run's authority, so it is
resolved once: the begin leg hands the verified claim id back on the case
contract, and the run carries it to every recording leg it fires when the
command finally exits.

A long gate needs that. An hour-long suite outlives the stale-session
sweep's TTL, so re-deriving authority at recording time asks whether the
session holds the claim *now* — a different question from whether it held
the claim when the run began. Answering the second question is what lets a
passing run record its own verdict instead of stranding the gate on a
claim that was reclaimed or handed off while the suite was still running.

A start-bound claim proves exactly what a live claim proves and no more:
the row has to name the calling session and target the same item, so a
session can only present authority it genuinely held. The window bounds
how long a released claim stays presentable, so this never becomes a
standing write capability on an item that has moved on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from yoke_core.domain.qa_constants import MAX_CASE_COMMAND_TIMEOUT_SECONDS
from yoke_core.domain.time_parse import parse_timestamp_utc

#: Payload key the case contract and every recording leg use to carry the
#: claim the run bound at its start.
PAYLOAD_KEY = "execution_claim_id"

#: How long after its release a start-bound claim still authorizes the run
#: it was bound to. Sized to the longest a single gate command may run, so
#: a run that spends its whole budget can still record its verdict, and no
#: longer.
AUTHORITY_WINDOW_SECONDS = MAX_CASE_COMMAND_TIMEOUT_SECONDS


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_start_bound_claim_id(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
) -> Optional[int]:
    """Return the claim id ``session_id`` holds on ``item_id`` right now.

    Called at the start of a run, where the dispatcher has just verified
    the same claim, so a miss here means the item is not session-claimed
    and the run simply carries no start-bound grant.
    """
    if not session_id:
        return None
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT id FROM work_claims "
        f"WHERE session_id = {p} AND target_kind = 'item' AND item_id = {p} "
        "AND released_at IS NULL ORDER BY id DESC LIMIT 1",
        (session_id, int(item_id)),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _claim_row(claim_id: int) -> Optional[tuple[Any, Any, Any]]:
    """Read ``(session_id, item_id, released_at)`` for one item claim.

    An unreadable claim grants nothing, so every failure — missing row,
    unreachable database — collapses to ``None`` rather than an exception
    a recording leg would have to interpret.
    """
    try:
        from yoke_core.domain import db_helpers

        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT session_id, item_id, released_at FROM work_claims "
                f"WHERE id = {p} AND target_kind = 'item'",
                (int(claim_id),),
            ).fetchone()
    except Exception:  # noqa: BLE001 - see docstring
        return None
    if row is None:
        return None
    if hasattr(row, "keys"):
        return (row["session_id"], row["item_id"], row["released_at"])
    return (row[0], row[1], row[2])


def start_bound_claim_grants(
    claim_id: int,
    *,
    session_id: str,
    item_id: int,
    now: Optional[datetime] = None,
) -> bool:
    """Whether ``claim_id`` still authorizes ``session_id`` on ``item_id``.

    The claim must name this session and target this item. A live claim
    grants outright; a released one grants only inside
    :data:`AUTHORITY_WINDOW_SECONDS` of its release, which covers a run
    that started before the release and finished after it.
    """
    if not session_id:
        return False
    row = _claim_row(claim_id)
    if row is None:
        return False
    claim_session, claim_item, released_at = row
    if str(claim_session or "") != session_id:
        return False
    if claim_item is None or int(claim_item) != int(item_id):
        return False
    if released_at is None:
        return True
    released = parse_timestamp_utc(released_at)
    if released is None:
        return False
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return released >= reference - timedelta(seconds=AUTHORITY_WINDOW_SECONDS)


def _presented_claim_id(payload: Any) -> Optional[int]:
    """Read the start-bound claim id a caller presented, if it sent one."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get(PAYLOAD_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def payload_authority(case: Any) -> dict:
    """The payload fragment a run's recording legs carry, from its case.

    Empty when the case bound no claim — an unclaimed subject records
    under whatever authority the recording leg can establish on its own.
    """
    claim_id = _presented_claim_id(case)
    return {} if claim_id is None else {PAYLOAD_KEY: claim_id}


def payload_grants_authority(
    payload: Any,
    *,
    session_id: str,
    item_id: int,
) -> bool:
    """Whether a recording leg's payload carries usable start-bound authority.

    Consulted only after the live-claim check has already failed, so a
    payload carrying no claim id costs one dict lookup.
    """
    claim_id = _presented_claim_id(payload)
    if claim_id is None:
        return False
    return start_bound_claim_grants(
        claim_id,
        session_id=session_id,
        item_id=item_id,
    )


__all__ = [
    "AUTHORITY_WINDOW_SECONDS",
    "PAYLOAD_KEY",
    "payload_authority",
    "payload_grants_authority",
    "resolve_start_bound_claim_id",
    "start_bound_claim_grants",
]
