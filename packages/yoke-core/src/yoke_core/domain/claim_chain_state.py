"""Claim / chain / epic-task freshness state — the post telemetry-only-events app-state owner.

The telemetry-only events cutover makes the ``events`` table telemetry-only: claim-acquire reason, release
intent, chain-checkpoint progress, and epic-task freshness move to
first-class columns — ``work_claims.reason`` / ``reason_intent`` /
``release_reason_intent``, ``harness_sessions.last_chain_step`` /
``last_checkpoint_at``, and ``epic_tasks.last_activity_at``. The claim
acquire/release paths, the chain-checkpoint writer, and the epic-task
mutation surfaces call the writers here in the same transaction as the
domain mutation; readers (``frontier_recent_owner``, ``idea_claim_events``,
``chain_head_freshness``, ``doctor_hc_routed_ownership``) consume only this
state, never the events ledger.

Column semantics mirror the release-side precedent (``release_reason`` =
canonical schema enum, intent = caller-supplied): ``work_claims.reason``
stores the verbatim acquire reason; ``reason_intent`` stores the canonical
vocabulary classification (NULL for free text). NULL anywhere means "no
state recorded" — readers treat it as absent, never fall back to events.

Schema-tolerance contract: many test fixtures build minimal ``work_claims``
/ ``harness_sessions`` / ``epic_tasks`` shapes. Every writer introspects via
``information_schema`` (the codebase's established minimal-fixture pattern)
and silently skips what the schema cannot hold.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns

# Canonical intent vocabulary for the claim-acquire ``--reason`` tag.
# Advisory — free-text reasons remain valid and land verbatim in
# ``work_claims.reason``; only vocabulary matches are classified into
# ``reason_intent`` so Ouroboros / doctor aggregations never second-guess
# prose. Published as CLI help via
# :mod:`yoke_core.api.service_client_work_claim_acquire_reason_help`.
ACQUIRE_INTENT_REASONS: tuple[str, ...] = (
    "draft-in-progress",
    "transition",
    "progress-log-append",
    "edit",
    "rewrite-in-progress",
    "engineer-dispatch",
    "scheduled-run",
    "idea-intake",
    "advance_run",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _columns(conn: Any, table: str) -> set:
    try:
        return set(_schema_get_columns(conn, table))
    except db_backend.operational_error_types():
        return set()


def classify_acquire_reason_intent(reason: Optional[str]) -> Optional[str]:
    """Return the canonical intent tag for *reason*, or ``None`` for free text."""
    if reason and reason in ACQUIRE_INTENT_REASONS:
        return reason
    return None


def claim_reason_columns_present(conn: Any) -> bool:
    return "reason" in _columns(conn, "work_claims")


def release_intent_column_present(conn: Any) -> bool:
    return "release_reason_intent" in _columns(conn, "work_claims")


def chain_state_columns_present(conn: Any) -> bool:
    return "last_chain_step" in _columns(conn, "harness_sessions")


def epic_task_activity_column_present(conn: Any) -> bool:
    return "last_activity_at" in _columns(conn, "epic_tasks")


def record_claim_reason(
    conn: Any, *, claim_id: int, reason: Optional[str],
) -> None:
    """Stamp ``reason`` + ``reason_intent`` on a freshly acquired claim row.

    Same-transaction companion to the ``work_claims`` INSERT. No-ops when
    the caller supplied no reason (NULL = no state recorded) or when the
    fixture schema lacks the columns.
    """
    if not reason or not claim_reason_columns_present(conn):
        return
    p = _p(conn)
    conn.execute(
        f"UPDATE work_claims SET reason = {p}, reason_intent = {p} "
        f"WHERE id = {p}",
        (reason, classify_acquire_reason_intent(reason), int(claim_id)),
    )


def record_release_intent(
    conn: Any, *, claim_id: int, intent: Optional[str],
) -> None:
    """Stamp the caller-supplied release intent on a released claim row.

    Same-transaction companion to the release UPDATE (the release is an
    UPDATE setting ``released_at`` — the row persists). Paths with no
    caller intent (reclaim sweeps, done-item cleanup) skip the call and
    leave NULL, matching the pre-cutover reader-visible state where no
    ``WorkReleased`` intent existed for those releases.
    """
    if not intent or not release_intent_column_present(conn):
        return
    p = _p(conn)
    conn.execute(
        f"UPDATE work_claims SET release_reason_intent = {p} WHERE id = {p}",
        (intent, int(claim_id)),
    )


def record_release_intent_for_session(
    conn: Any, *, session_id: str, released_at: str, intent: Optional[str],
) -> None:
    """Bulk-release variant: stamp intent on every row this release touched."""
    if not intent or not release_intent_column_present(conn):
        return
    p = _p(conn)
    conn.execute(
        f"UPDATE work_claims SET release_reason_intent = {p} "
        f"WHERE session_id = {p} AND released_at = {p}",
        (intent, session_id, released_at),
    )


def stamp_chain_checkpoint(
    conn: Any, *, session_id: str, step: int, at: str,
) -> None:
    """Stamp ``last_chain_step`` + ``last_checkpoint_at`` on the session row.

    Same-transaction companion to the offer-envelope checkpoint write in
    :func:`yoke_core.domain.sessions_queries_chain.update_chain_checkpoint`.
    Unlike the envelope (clobbered by later offers), these columns are
    monotonic per session and survive re-offers.
    """
    if not chain_state_columns_present(conn):
        return
    p = _p(conn)
    conn.execute(
        f"UPDATE harness_sessions SET last_chain_step = {p}, "
        f"last_checkpoint_at = {p} WHERE session_id = {p}",
        (int(step), at, session_id),
    )


def touch_epic_task_activity(
    conn: Any, *, epic_id: Any, task_num: Any, at: Optional[str] = None,
) -> None:
    """Stamp ``epic_tasks.last_activity_at`` for one task.

    Called by every agent-meaningful epic-task mutation (status writes via
    ``item_status_transitions``, body / field updates, progress notes,
    epic-task-targeted claim acquire) so ``chain_head_freshness`` reads
    task recency from state instead of scanning the events ledger.
    """
    try:
        numeric_epic = int(str(epic_id).strip().upper().replace("YOK-", ""))
        numeric_task = int(task_num)
    except (TypeError, ValueError):
        return
    if not epic_task_activity_column_present(conn):
        return
    if at is None:
        from datetime import datetime, timezone

        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p = _p(conn)
    # str(epic_id) matches the epic CRUD convention — coerces cleanly
    # whether the fixture declared epic_id as INTEGER or TEXT.
    conn.execute(
        f"UPDATE epic_tasks SET last_activity_at = {p} "
        f"WHERE epic_id = {p} AND task_num = {p}",
        (at, str(numeric_epic), numeric_task),
    )


__all__ = [
    "ACQUIRE_INTENT_REASONS",
    "chain_state_columns_present",
    "claim_reason_columns_present",
    "classify_acquire_reason_intent",
    "epic_task_activity_column_present",
    "record_claim_reason",
    "record_release_intent",
    "record_release_intent_for_session",
    "release_intent_column_present",
    "stamp_chain_checkpoint",
    "touch_epic_task_activity",
]
