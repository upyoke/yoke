"""What the stale sweep does about a session parked on a release wait.

:mod:`release_wait_ownership` says what a release-wait owner IS; this says
what may happen to one when it goes quiet, which is the decision the sweep
was getting wrong. Two outcomes, deliberately different facts:

* An owner that parked, holds nothing but its waits, is not reported gone,
  and is still inside the retention bound is waiting BY DESIGN. It is
  spared, so its claim survives until the item reaches done.
* Anything else is gone as far as the control plane can tell. It is
  reclaimed, and its items are named to the project's steering seat -- an
  explicit restaffing fact, never a silent release.

The spare is bounded on purpose. Sparing forever would let one holder whose
machine never came back pin its item open with nobody hearing about it, and
the stale-alive probe will not chase that holder either: it skips parked
sessions by design, which is exactly the population this protects. So the
spare ends at a relay-reported death the product still calls unaccounted
for, or at a generous retention bound -- and both ends hand the item over
rather than dropping it.

It is scoped, too. Sparing a session spares every claim it holds, so a
holder carrying anything beyond its own release waits is not spared at all;
its item still reaches steering, which is the outcome that matters.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from yoke_core.domain.release_wait_ownership import owned_release_waits
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_mode import SESSION_MODE_PARKED
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.work_claim_target_sql import (
    LIVENESS_BOUND_SQL,
    scope_int_sql,
)

if TYPE_CHECKING:  # the classifier's own import chain pulls the harness
    from yoke_core.domain.session_reclaim_activity import ReclaimClassification

#: The reclaim classification reason a spared release-wait owner reports.
REASON_RELEASE_WAIT_OWNER = "release_wait_owner"

#: Multiples of the holdings TTL a declared release-wait owner is spared
#: for before the sweep reclaims it and hands its item to steering.
RELEASE_WAIT_TTL_MULTIPLIER = 7

#: One hand-off notice per item and the session that abandoned its wait.
HANDOFF_KEY_PREFIX = "release-wait-handoff:"


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _session_mode(conn: Any, session_id: str) -> str:
    if not _table_exists(conn, "harness_sessions"):
        return ""
    row = conn.execute(
        "SELECT mode FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    return str(row["mode"] or "") if row is not None else ""


def waiting_by_design(conn: Any, session_id: str) -> bool:
    """True when this session declared its wait by parking."""
    return _session_mode(conn, session_id) == SESSION_MODE_PARKED


def _other_liveness_bound_claims(conn: Any, session_id: str, waits: Any) -> int:
    """Count this session's other reclaimable claims, outside its waits."""
    if not _table_exists(conn, "work_claims"):
        return 0
    item_id = scope_int_sql(conn, "scope", "item_id")
    held = tuple(int(entry["item_id"]) for entry in waits)
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM work_claims WHERE released_at IS NULL "
        f"AND session_id=%s AND {LIVENESS_BOUND_SQL} "
        f"AND NOT (target_kind='item' AND {item_id} IN ("
        + ",".join("%s" for _ in held)
        + "))",
        (session_id, *held),
    ).fetchone()
    return int(row["cnt"] or 0) if row is not None else 0


def _quiet_past_retention(conn: Any, session_id: str, now: datetime) -> bool:
    """Whether this owner has been quiet past the release-wait retention.

    The spare has to be bounded or a holder whose machine never comes back
    pins its item open forever, and the stale-alive probe will not chase it
    either — that probe skips parked sessions by design. The bound is a
    multiple of the holdings TTL rather than a new knob, mirroring
    ``IN_FLIGHT_HARD_TTL_MULTIPLIER``: a real delivery plus its post-deploy
    validation is hours, so a week of silence is generous by any reading and
    still ends in a named hand-off rather than in silence.
    """
    from yoke_core.domain.session_reclaim_activity import read_activity_signals
    from yoke_core.domain.sessions_analytics_core import (
        DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
    )

    ttl = DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES * RELEASE_WAIT_TTL_MULTIPLIER
    try:
        activity = read_activity_signals(conn, session_id).activity_at
    except Exception:  # noqa: BLE001 - an unreadable stamp is not protection
        return True
    return activity_is_stale(activity, executor=None, now=now, base_ttl_minutes=ttl)


def _process_is_gone(conn: Any, session_id: str) -> bool:
    """Whether the relay's process-death record still stands unaccounted for.

    :func:`current_native_process_observation` already knows that a parked
    session whose native exited cleanly is a headless command ending its
    turn, not a disappearance — the relay resumes that session on the next
    wake. So this asks the same question the rest of the product asks and
    only treats what IT still calls gone as gone: an abnormal exit, or one
    nobody measured.
    """
    if not _table_exists(conn, "harness_sessions"):
        return False
    try:
        row = conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session_id,)
        ).fetchone()
    except Exception:  # noqa: BLE001 - an unreadable row proves no death
        return False
    if row is None:
        return False
    return current_native_process_observation(dict(row)) is not None


def guard_release_wait_owner(
    conn: Any,
    session_id: str,
    classification: "ReclaimClassification",
    *,
    now: Optional[datetime] = None,
) -> "ReclaimClassification":
    """Refuse a reclaim that would strip a live, declared release-wait owner.

    ``classification`` is whatever :func:`session_reclaim_activity.
    classify_reclaimable` decided; this returns it unchanged unless every
    condition for sparing holds, in which case the reclaim is aborted with
    :data:`REASON_RELEASE_WAIT_OWNER`. The sweep already emits its
    ``ReclaimAborted`` evidence from that reason, so a spared owner is a
    named, queryable fact rather than a silent exemption.

    Four things must be true, and each one that is not is a reason the
    sweep should proceed and hand the item to steering instead:

    * the session declared its wait by parking — an undeclared quiet holder
      is gone as far as the control plane can tell;
    * its release waits are ALL it holds. Sparing a session spares every
      claim on it, so a holder carrying unrelated claims would pin those
      open too; the item still reaches steering, which is the outcome that
      matters;
    * the relay does not still report its process gone unaccounted for;
    * it has not been quiet past the release-wait retention bound.

    A session whose row has already ended is past this protection too: its
    holdings are settled by the end path, and pinning them open here would
    leave an item owned by nobody that can act on it.
    """
    from yoke_core.domain.session_reclaim_activity import ReclaimClassification

    if not classification.is_reclaimable:
        return classification
    if not waiting_by_design(conn, session_id):
        return classification
    waits = owned_release_waits(conn, session_id)
    if not waits:
        return classification
    if _other_liveness_bound_claims(conn, session_id, waits):
        return classification
    if _process_is_gone(conn, session_id):
        return classification
    if _quiet_past_retention(conn, session_id, _now(now)):
        return classification
    return ReclaimClassification(
        is_reclaimable=False,
        reason=REASON_RELEASE_WAIT_OWNER,
        evidence=classification.evidence,
    )


def handoff_idempotency_key(item_id: int, session_id: str) -> str:
    """One hand-off per item and the session that stopped answering for it."""
    return f"{HANDOFF_KEY_PREFIX}{item_id}:{session_id}"


def handoff_message(*, public_ref: str, session_id: str, route: str) -> str:
    """Name the abandoned wait, and what the reader has to decide."""
    who = "You are" if route == "holder" else "This seat is"
    return (
        f"{public_ref} is at its release wait and its owner is gone: session "
        f"{session_id} held the item's work claim, never declared a "
        f"deployment wait, and the stale sweep reclaimed it. The merge "
        f"landed and the delivery still owes this item a close-out, so the "
        f"item is now unowned rather than finished. {who} the addressable "
        f"owner of that gap: staff a session at `/yoke dash {public_ref}` to "
        f"finish the close-out once its delivery clears, or close the item "
        f"out directly with `yoke merge item {public_ref} --result ... "
        f"--verification ...`."
    )


def hand_off_release_wait(
    conn: Any,
    session_id: str,
    owned: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Tell steering about each release wait this reclaim just orphaned.

    Called AFTER the claim is released on purpose: the notice resolves its
    own recipient from the live claim, so sending before the release would
    address the very session the sweep just decided is gone.

    A delivery failure here never reverses the reclaim, which has already
    committed. It is reported per item so an operator can see which
    hand-off did not land.
    """
    from yoke_core.domain.merge_queue_landing_notice import push_notice

    results: list[dict[str, Any]] = []
    if not owned:
        return results
    stamp = _now(now)
    for entry in owned:
        public_ref = str(entry["public_ref"])
        try:
            delivery = push_notice(
                conn,
                item_id=int(entry["item_id"]),
                project_id=int(entry["project_id"]),
                body_for_route=lambda route, ref=public_ref: handoff_message(
                    public_ref=ref, session_id=session_id, route=route
                ),
                idempotency_key=handoff_idempotency_key(
                    int(entry["item_id"]), session_id
                ),
                now=stamp,
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - never reverses a reclaim
            conn.rollback()
            delivery = f"failed: {exc}"
        results.append({"public_ref": public_ref, "delivery": delivery})
    return results


__all__ = [
    "HANDOFF_KEY_PREFIX",
    "REASON_RELEASE_WAIT_OWNER",
    "RELEASE_WAIT_TTL_MULTIPLIER",
    "guard_release_wait_owner",
    "hand_off_release_wait",
    "handoff_idempotency_key",
    "handoff_message",
    "waiting_by_design",
]
