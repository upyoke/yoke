"""Who owns an item that has merged and is still waiting on its delivery.

A Dash whose merge lands at the pinned release wait is not finished. Its
delivery still has to run, its post-deploy validation still has to be
walked, and only then does the item reach done. The session that merged it
is the one carrying that context, so it keeps the item's work claim and
waits rather than reporting and ending.

Keeping the claim was already what the close-out transition did, and it was
the only path that agreed. The launched-worker mandate told every session to
END after its DONE report, the Dash close-out offered a claim release beside
it, and the stale sweep reclaimed whatever went quiet -- so one retained
claim was undone by three separate paths, and an item at its release wait
was left unowned more often than it was held. This module is the single
place that says what a release-wait owner is and what may happen to it; the
mandate, the merge close-out, and the sweep all read it from here rather
than each carrying its own idea.

Two dispositions are possible for such an owner, and they are deliberately
different facts:

* An owner that parked with its wait declared is waiting BY DESIGN. The
  sweep spares it, so its claim survives until the item reaches done.
* An owner that went quiet without declaring anything is gone as far as the
  control plane can tell. It is reclaimed, and its item is handed to the
  project's steering seat by name -- an explicit restaffing fact, never a
  silent release.

The park itself is stamped by the merge close-out rather than left to the
worker to remember -- that write is :mod:`release_wait_park`, which
relays instead of connecting because it runs installed-client side.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_mode import SESSION_MODE_PARKED
from yoke_core.domain.work_claim_targets import scope_int_sql
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row

if TYPE_CHECKING:  # the classifier's own import chain pulls the harness
    from yoke_core.domain.session_reclaim_activity import ReclaimClassification

#: The reclaim classification reason a spared release-wait owner reports.
REASON_RELEASE_WAIT_OWNER = "release_wait_owner"

#: One hand-off notice per item and the session that abandoned its wait.
HANDOFF_KEY_PREFIX = "release-wait-handoff:"

TOUCH_FUNCTION = "sessions.touch"
HOLDER_FUNCTION = "claims.work.holder_get"


RELEASE_WAIT_RETENTION_TEACHING = (
    "A merge that lands your item at its pinned release wait is a completed "
    "merge that is NOT a finished item: the delivery still has to run and "
    "its post-deploy validation still has to be walked before the item "
    "reaches done. That close-out therefore keeps your work claim and parks "
    "your session with the wait named, and you keep both. Do NOT release the "
    "claim and do NOT end your session there — report what landed in your "
    "own output, say you are waiting on delivery, and stop deliberately. The "
    "deployment wake re-enters you when your delivery clears or its QA stage "
    "needs you; re-run the same `yoke merge item` command with --result and "
    "--verification then, and it finishes the close-out. Only once the item "
    "reaches done do you send the DONE report and end. A release-wait owner "
    "that goes quiet without that park is treated as gone and its item is "
    "handed to steering, so the park is what keeps the item yours."
)


def park_reason(public_ref: str) -> str:
    """The concrete deployment wait a parked release-wait owner declares."""
    named = (public_ref or "").strip() or "this item"
    return (
        f"awaiting {named} delivery: deployment run, then post-deploy "
        f"validation and the done close-out"
    )


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def owned_release_waits(conn: Any, session_id: str) -> list[dict[str, Any]]:
    """Items at their pinned release wait whose claim ``session_id`` holds.

    An unreadable pin answers "not a release wait" for that item alone: a
    definition this call cannot interpret is not evidence that the sweep
    should spare a session, and treating it as one would let a corrupt row
    pin a claim open forever.
    """
    required = ("work_claims", "items", "projects", "workflow_versions")
    if not session_id or not all(_table_exists(conn, name) for name in required):
        return []
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    rows = conn.execute(
        f"SELECT i.id AS item_id,i.project_id,i.status,i.project_sequence,"
        "i.workflow_id,i.workflow_version_id,p.public_item_prefix,"
        "v.version,v.definition_json,v.definition_digest "
        "FROM work_claims wc "
        f"JOIN items i ON i.id={item_id} "
        "JOIN projects p ON p.id=i.project_id "
        "JOIN workflow_versions v ON v.id=i.workflow_version_id "
        "WHERE wc.released_at IS NULL AND wc.target_kind='item' "
        "AND wc.session_id=%s ORDER BY i.id",
        (session_id,),
    ).fetchall()
    owned: list[dict[str, Any]] = []
    for row in rows:
        try:
            runtime = workflow_runtime_from_row(row)
            release_stage = delivery_redirect_stage(runtime)
        except Exception:  # noqa: BLE001 - an unreadable pin spares nothing
            continue
        if release_stage is None or str(row["status"] or "") != release_stage:
            continue
        owned.append(
            {
                "item_id": int(row["item_id"]),
                "project_id": int(row["project_id"]),
                "public_ref": format_item_ref(
                    None, row["public_item_prefix"], row["project_sequence"]
                ),
                "status": release_stage,
            }
        )
    return owned


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


def guard_release_wait_owner(
    conn: Any,
    session_id: str,
    classification: "ReclaimClassification",
) -> "ReclaimClassification":
    """Refuse a reclaim that would strip a declared release-wait owner.

    ``classification`` is whatever :func:`session_reclaim_activity.
    classify_reclaimable` decided; this returns it unchanged unless the
    session is a parked owner of an item at its pinned release wait, in
    which case the reclaim is aborted with
    :data:`REASON_RELEASE_WAIT_OWNER`. The sweep already emits its
    ``ReclaimAborted`` evidence from that reason, so the spared owner is a
    named, queryable fact rather than a silent exemption.

    A session whose row has already ended is past this protection: its
    holdings are settled by the end path, and pinning them open here would
    leave an item owned by nobody that can act on it.
    """
    from yoke_core.domain.session_reclaim_activity import ReclaimClassification

    if not classification.is_reclaimable:
        return classification
    if not waiting_by_design(conn, session_id):
        return classification
    if not owned_release_waits(conn, session_id):
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
    "HOLDER_FUNCTION",
    "REASON_RELEASE_WAIT_OWNER",
    "RELEASE_WAIT_RETENTION_TEACHING",
    "TOUCH_FUNCTION",
    "guard_release_wait_owner",
    "hand_off_release_wait",
    "handoff_idempotency_key",
    "handoff_message",
    "owned_release_waits",
    "park_reason",
    "waiting_by_design",
]
