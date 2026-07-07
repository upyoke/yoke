"""Draft-claim observability for ``/yoke idea`` paired-layer guard.

Owns the small surface that turns a ``release-work-claim --reason
idea-complete`` call into an ``IdeaClaimHeld`` event with duration and
provenance metadata. Lives in its own module so
:mod:`yoke_core.domain.sessions_lifecycle_release` does not need to grow
past its line cap to handle draft-claim event assembly.

The release path delegates to :func:`emit_if_idea_release` after the
``WorkReleased`` event has already fired — a bare release intent of
``idea-complete`` is the operator-asserted signal that this claim was held
for ``/yoke idea`` body composition. The emitter looks up the original
claim row to recover the acquire-time reason
(``work_claims.reason_intent`` / ``reason``, ``draft-in-progress`` in the
canonical case — first-class claim state since the telemetry-only events cutover), computes the held
duration, and emits the event.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from yoke_core.domain import db_backend


CLAIM_REASON_DRAFT = "draft-in-progress"
RELEASE_REASON_IDEA_COMPLETE = "idea-complete"
EVENT_NAME = "IdeaClaimHeld"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def is_idea_release_intent(release_reason_intent: Optional[str]) -> bool:
    """Return True when the operator-supplied release intent identifies an idea-phase draft."""
    return release_reason_intent == RELEASE_REASON_IDEA_COMPLETE


def compute_duration_ms(claimed_at_iso: Optional[str], released_at_iso: Optional[str]) -> int:
    """Return clamped non-negative milliseconds between two ISO timestamps."""
    if not claimed_at_iso or not released_at_iso:
        return 0
    try:
        c = _parse_iso(claimed_at_iso)
        r = _parse_iso(released_at_iso)
    except ValueError:
        return 0
    delta_ms = int((r - c).total_seconds() * 1000)
    return max(0, delta_ms)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, normalizing trailing ``Z`` to ``+00:00``."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _lookup_claim_row(conn: Any, claim_id: int) -> Optional[Dict[str, Any]]:
    p = _p(conn)
    row = conn.execute(
        "SELECT claimed_at, released_at, item_id, session_id "
        f"FROM work_claims WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return {
        "claimed_at": row[0],
        "released_at": row[1],
        "item_id": row[2],
        "session_id": row[3],
    }


def _lookup_claim_reason_intent(conn: Any, claim_id: int) -> Optional[str]:
    """Return the acquire-time reason recorded on the claim row, if present.

    Reads ``work_claims.reason_intent`` (the canonical-vocabulary
    classification) with the verbatim ``reason`` as the free-text
    fallback — both written by the acquire path at INSERT time (telemetry-only events cutover:
    first-class claim state, never the events ledger). Tolerates fixture
    schemas without the columns by returning ``None``.
    """
    p = _p(conn)
    try:
        row = conn.execute(
            "SELECT COALESCE(reason_intent, reason) AS intent "
            f"FROM work_claims WHERE id = {p}",
            (int(claim_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn=conn):
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    if row is None:
        return None
    value = row["intent"] if hasattr(row, "keys") else row[0]
    return value if isinstance(value, str) else None


def emit_if_idea_release(
    conn: Any,
    *,
    session_id: str,
    target_item_id: Optional[int],
    claim_id: int,
    release_reason_intent: str,
    released_at: str,
) -> bool:
    """Emit ``IdeaClaimHeld`` when the release intent identifies a draft completion.

    Returns ``True`` when the event was emitted, ``False`` otherwise. Failures
    are best-effort — the surrounding release flow does not block on missing
    context or failed event emission.
    """
    if not is_idea_release_intent(release_reason_intent):
        return False
    if target_item_id is None or claim_id is None:
        return False

    claim_row = _lookup_claim_row(conn, int(claim_id))
    claimed_at = claim_row.get("claimed_at") if claim_row else None
    duration_ms = compute_duration_ms(claimed_at, released_at)
    claim_reason_intent = _lookup_claim_reason_intent(conn, int(claim_id))

    payload: Dict[str, Any] = {
        "claim_id": int(claim_id),
        "claimed_at": claimed_at,
        "released_at": released_at,
        "duration_ms": duration_ms,
        "claim_reason_intent": claim_reason_intent,
        "release_reason_intent": release_reason_intent,
    }

    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            EVENT_NAME,
            event_kind="lifecycle",
            event_type="idea_claim_lifecycle",
            source_type="api",
            severity="INFO",
            outcome="completed",
            session_id=session_id,
            item_id=str(target_item_id),
            context=payload,
            conn=conn,
        )
        return True
    except Exception:
        return False


__all__ = [
    "CLAIM_REASON_DRAFT",
    "EVENT_NAME",
    "RELEASE_REASON_IDEA_COMPLETE",
    "compute_duration_ms",
    "emit_if_idea_release",
    "is_idea_release_intent",
]
