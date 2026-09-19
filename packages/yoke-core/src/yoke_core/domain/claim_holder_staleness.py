"""Whether a claim holder's silence makes its claim reclaimable.

A holder that stopped calling tools looks exactly like one that died, and the
inactivity TTL is what usually separates them. It cannot separate the third
case: a session that went quiet on purpose. A worker parked at a release wait
is doing what it was told to do — it will not call a tool again until its
deployment wake arrives, which outlasts any TTL — so reading its claim as
reclaimable offers its item to steering while the owner is still holding it.

Parking is a declaration, and this predicate honours it: a parked holder is
exempt from inactivity staleness, and from other viewers its claim keeps
reading as held by a live session. The exemption is not immortality. An ended
session and a confirmed-gone native process are real deaths rather than
declared waits — the idle-holder alarm reports them on their own — and both
still read stale here. A clean native exit under a park is not one of them:
that is the ordinary end of a headless command whose session is waiting,
which :func:`current_native_process_observation` already accounts for.

Every reader that derives claim reclaimability from staleness asks this one
question — the scheduler's claim states, the fleet report and offer
candidates that read them, and the rechecks that actually release a claim
row — so a parked holder cannot read live to one and reclaimable to the next.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)

#: Why a reclaim stopped short of a holder that read stale on its timestamps
#: alone, recorded on the ``ReclaimAborted`` event the reclaim already emits.
REASON_PARKED_HOLDER = "parked_holder"

#: What :func:`holder_claim_is_stale` reads off a holder's session row. The
#: process observation needs its own evidence plus the activity that could
#: supersede it, so the set is wider than mode and ``ended_at``.
HOLDER_SESSION_COLUMNS = (
    "session_id",
    "ended_at",
    "mode",
    "native_process_gone_at",
    "native_process_gone_evidence",
    "last_heartbeat",
    "last_tool_call_at",
    "episode_started_at",
    "turn_posture",
    "turn_posture_at",
)


def holder_claim_is_stale(
    row: Mapping[str, Any],
    *,
    inactivity_stale: bool,
) -> bool:
    """Whether this holder's claim reads reclaimable to another viewer.

    ``inactivity_stale`` is the caller's own TTL verdict about the holder's
    last activity. It decides nothing on its own for a parked holder.
    """
    if row.get("ended_at") is not None:
        return True
    if current_native_process_observation(row) is not None:
        return True
    if session_is_parked(row.get("mode")):
        return False
    return bool(inactivity_stale)


def parked_claim_holders(
    conn: Any,
    session_ids: Iterable[Any],
) -> frozenset[str]:
    """The holders whose park exempts them from inactivity staleness.

    One query for the whole set, so a board of claims does not ask per row.
    A holder outside the returned set is judged by its caller's TTL exactly
    as before — including a parked session that has ended or whose native
    process is confirmed gone.
    """
    wanted = sorted({str(value) for value in session_ids if value})
    if not wanted:
        return frozenset()
    try:
        available = set(_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types(conn):
        _rollback(conn)
        return frozenset()
    columns = [name for name in HOLDER_SESSION_COLUMNS if name in available]
    if "session_id" not in columns or "mode" not in columns:
        # Without the mode stamp no row can declare a park, so nothing here
        # is exempt and the caller's TTL verdict stands unchanged.
        return frozenset()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in wanted)
    try:
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM harness_sessions "
            f"WHERE session_id IN ({placeholders})",
            tuple(wanted),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        _rollback(conn)
        return frozenset()
    exempt = set()
    for row in rows:
        record = _record(row, columns)
        # Asked with the TTL already saying "stale": a holder that still
        # answers "not stale" is one the park is protecting.
        if holder_claim_is_stale(record, inactivity_stale=True):
            continue
        holder = str(record.get("session_id") or "")
        if holder:
            exempt.add(holder)
    return frozenset(exempt)


def _record(row: Any, columns: list[str]) -> dict[str, Any]:
    """One holder row as a mapping, whatever row shape the engine returns."""
    if hasattr(row, "keys"):
        return {name: row[name] for name in columns}
    return dict(zip(columns, tuple(row)))


def _rollback(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        try:
            conn.rollback()
        except Exception:
            pass


__all__ = [
    "HOLDER_SESSION_COLUMNS",
    "REASON_PARKED_HOLDER",
    "holder_claim_is_stale",
    "parked_claim_holders",
]
