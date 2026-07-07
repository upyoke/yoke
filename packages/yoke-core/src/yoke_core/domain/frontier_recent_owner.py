"""Routed-ownership exclusion helper for ``compute_frontier``.

Yoke's router treats a live, item-scoped session as the owner of its
routed item even when the underlying ``work_claims`` row is briefly
released. Two release shapes leave the owner alive:

1. ``session_ended``: the SessionEnd hook force-releases on a transient
   signal (laptop sleep, app reload, idle timeout). The session is alive
   inside the recovery window; another sweep MUST NOT re-route the item.
2. **Non-terminal release intent**: the owning handler released its own
   claim with a ``readiness-check-blocked`` intent (or any other
   non-terminal intent from :mod:`release_intent_classification`) and
   intends to resume the moment the precondition clears. The DB-stored
   ``release_reason`` for this shape is ``released``; the intent is
   first-class claim state on ``work_claims.release_reason_intent``,
   stamped by the release paths at release time. The events ledger is
   telemetry-only and is never consulted here.

This module returns the per-item details the frontier needs to defend
those items for the duration of the recovery window. The requesting
session is never defended against itself — that case is owned by the
conditional auto-reacquire path in
:mod:`sessions_lifecycle_reactivation`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import db_backend
from .release_intent_classification import is_non_terminal_release_intent
from .schema_common import _get_columns as _schema_get_columns
from .session_reclaim_activity import latest_activity


# Latest released claim per item, joined to the still-live owner session.
# The release intent is read straight off the claim row; the
# ``{intent_expr}`` placeholder renders ``wc.release_reason_intent`` when
# the column exists and ``NULL`` on minimal fixture schemas without it.
# Liveness derivation routes through :func:`latest_activity`
# (last_tool_call_at + heartbeats) post-fetch; the SQL no longer reads
# ``harness_sessions.last_heartbeat`` directly.
_DEFENDED_CLAIM_SQL = """
SELECT
    wc.id AS claim_id,
    wc.item_id,
    wc.session_id,
    wc.released_at,
    wc.release_reason,
    hs.offer_envelope,
    {intent_expr} AS release_intent
FROM work_claims wc
JOIN harness_sessions hs ON hs.session_id = wc.session_id
WHERE wc.released_at IS NOT NULL
  AND wc.target_kind = 'item'
  AND wc.item_id IS NOT NULL
  AND hs.ended_at IS NULL
  AND wc.id = (
    SELECT MAX(wc2.id)
    FROM work_claims wc2
    WHERE wc2.target_kind = 'item'
      AND wc2.item_id = wc.item_id
  )
ORDER BY wc.id DESC
"""


def _parse_iso(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _checkpoint_outcome(offer_envelope_raw: Any) -> Optional[str]:
    """Extract ``handler_outcome`` from the owner's chain checkpoint, if any."""
    if not offer_envelope_raw:
        return None
    try:
        envelope = json.loads(str(offer_envelope_raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    checkpoint = envelope.get("chain_checkpoint") if isinstance(envelope, dict) else None
    if not isinstance(checkpoint, dict):
        return None
    outcome = checkpoint.get("handler_outcome")
    return str(outcome) if outcome is not None else None


def _classify_defense(
    release_reason: Optional[str], release_intent: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(defense_class, release_reason_intent)`` or ``(None, ...)``.

    The first element is ``None`` when neither branch applies; callers
    skip those rows. Branch precedence: ``session_ended`` wins over the
    non-terminal-intent branch when both somehow match the same row.
    """
    if release_reason == "session_ended":
        return ("session_ended", "session_ended")
    if release_intent and is_non_terminal_release_intent(release_intent):
        return ("non_terminal_intent", release_intent)
    return (None, release_intent)


def routed_ownership_exclusions(
    conn: Any,
    *,
    window_s: int,
    requesting_session_id: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Map ``YOK-N`` -> defended-item detail dict (keyed by item id).

    Defended items have a most-recent release inside ``window_s`` whose
    owner session is still alive (no ``ended_at``, fresh activity also
    inside ``window_s``) AND either (a) was released with
    ``release_reason='session_ended'`` or (b) carries a non-terminal
    ``release_reason_intent`` on the claim row. Returns an empty mapping
    when the schema is missing or no rows qualify — frontier callers
    treat empty as "no defense".
    """
    now = datetime.now(timezone.utc)
    excluded: Dict[str, Dict[str, Any]] = {}
    try:
        claim_columns = set(_schema_get_columns(conn, "work_claims"))
        intent_expr = (
            "wc.release_reason_intent"
            if "release_reason_intent" in claim_columns
            else "NULL"
        )
        rows = conn.execute(
            _DEFENDED_CLAIM_SQL.format(intent_expr=intent_expr)
        ).fetchall()
    except db_backend.operational_error_types(conn):
        # Missing schema — frontier callers treat the empty mapping as
        # "no defense". On Postgres the failed statement aborts the
        # surrounding transaction, so roll back to leave the connection
        # usable for any subsequent query the caller makes.
        conn.rollback()
        return excluded

    seen_items: set[int] = set()
    for row in rows:
        item_id = row["item_id"]
        item_num = int(item_id) if item_id is not None else 0
        if not item_num or item_num in seen_items:
            continue
        owner_session = row["session_id"]
        if requesting_session_id and owner_session == requesting_session_id:
            continue
        defense_class, intent = _classify_defense(
            row["release_reason"], row["release_intent"],
        )
        if defense_class is None:
            continue
        released_dt = _parse_iso(row["released_at"])
        if released_dt is None or (now - released_dt).total_seconds() > window_s:
            continue
        activity_at = latest_activity(conn, owner_session)
        hb_dt = _parse_iso(activity_at)
        if hb_dt is None or (now - hb_dt).total_seconds() > window_s:
            continue
        seen_items.add(item_num)
        excluded[f"YOK-{item_num}"] = {
            "item_id": f"YOK-{item_num}",
            "prior_owner_session_id": owner_session,
            "released_at": str(row["released_at"]),
            "last_heartbeat": str(activity_at) if activity_at else "",
            "release_reason": row["release_reason"],
            "release_reason_intent": intent,
            "latest_claim_id": int(row["claim_id"]),
            "defense_class": defense_class,
            "checkpoint_outcome": _checkpoint_outcome(row["offer_envelope"]),
        }
    return excluded


__all__ = ["routed_ownership_exclusions"]
