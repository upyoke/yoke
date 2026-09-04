"""Workers this project lost to the model provider, and who owes them next.

A turn the provider ends leaves no trace in the ordinary detectors. The
session is live, its claim is held, its item is in progress, and it will
never speak again on its own — so it reads as a worker quietly thinking
and drops off the report entirely once someone stops finding that odd. On
2026-09-03 five workers sat that way for twenty minutes while the seat
read a report that said nothing was wrong.

The row exists so that never reads as silence. Each one names the session,
the item it holds, what the provider said, and when — and then the part
that decides whether the seat has anything to do: whether the relay is
going to resume it, or whether nobody is coming.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_vendor_error_states import vendor_error_states
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker


#: Statuses no further poll will act on. Everything else the relay owns,
#: and a row the relay owns is context for the seat rather than work.
SEAT_OWNED_STATUSES = frozenset({"budget_spent", "seat_required"})


@dataclass(frozen=True)
class VendorErrorSession:
    """One live session whose last turn the model provider ended."""

    session_id: str
    item_id: int
    public_ref: str
    signature_id: str
    error_message: str
    observed_at: str
    stopped_seconds: int
    status: str
    reason: str
    #: When the next resume comes due, empty when none is coming.
    due_at: str
    attempts: int
    budget: int
    executor_surface: str
    executor_version: str

    @property
    def seat_owed(self) -> bool:
        """Whether this row is the seat's to act on rather than the relay's."""
        return self.status in SEAT_OWNED_STATUSES


def _claimed_items(conn: Any, session_ids: Sequence[str]) -> dict[str, int]:
    """The item each of these sessions holds a work claim on, if any."""
    if not session_ids:
        return {}
    from yoke_core.domain.work_claim_targets import scope_int_sql

    item_id = scope_int_sql(conn, "c.scope", "item_id")
    slots = ",".join(marker(conn) for _ in session_ids)
    rows = conn.execute(
        f"SELECT c.session_id AS session_id, {item_id} AS item_id "
        "FROM work_claims c "
        f"WHERE c.target_kind='item' AND c.released_at IS NULL "
        f"AND c.session_id IN ({slots})",
        tuple(session_ids),
    ).fetchall()
    claimed: dict[str, int] = {}
    for raw in rows:
        record = dict(raw)
        try:
            claimed[str(record["session_id"])] = int(record["item_id"])
        except (TypeError, ValueError):
            continue
    return claimed


def _row(
    state: Mapping[str, Any],
    *,
    item_id: int,
    public_ref: str,
    now: str,
) -> VendorErrorSession:
    observed_at = str(state.get("observed_at") or "")
    return VendorErrorSession(
        session_id=str(state.get("session_id") or ""),
        item_id=item_id,
        public_ref=public_ref,
        signature_id=str(state.get("signature_id") or ""),
        error_message=str(state.get("error_message") or ""),
        observed_at=observed_at,
        stopped_seconds=age_seconds(observed_at, now) or 0,
        status=str(state.get("status") or ""),
        reason=str(state.get("reason") or ""),
        due_at=str(state.get("due_at") or ""),
        attempts=int(state.get("attempts") or 0),
        budget=int(state.get("budget") or 0),
        executor_surface=str(state.get("executor_surface") or ""),
        executor_version=str(state.get("executor_version") or ""),
    )


def vendor_error_sessions(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[VendorErrorSession, ...]:
    """This project's vendor-stopped sessions, in the order they stopped.

    The states themselves come from the same reader the relay's resume
    sweep consults, so a row saying the relay will retry and a relay that
    retries cannot come apart. This adds only what a steerer needs and a
    relay does not: which item is stalled behind each stopped worker.
    """
    states = vendor_error_states(
        conn,
        authorized_projects=(int(project_id),),
        now=parse_timestamp(now),
    )
    if not states:
        return ()
    claimed = _claimed_items(
        conn, [str(state.get("session_id") or "") for state in states]
    )
    refs = render_item_refs(conn, sorted(set(claimed.values())))
    rows = [
        _row(
            state,
            item_id=claimed.get(str(state.get("session_id") or ""), 0),
            public_ref=refs.get(claimed.get(str(state.get("session_id") or ""), 0), ""),
            now=now,
        )
        for state in states
    ]
    return tuple(sorted(rows, key=lambda entry: (entry.observed_at, entry.session_id)))


__all__ = ["SEAT_OWNED_STATUSES", "VendorErrorSession", "vendor_error_sessions"]
