"""Shared resolver for the ``--current-episode`` audit filter.

A single ``session_id`` may legitimately span multiple episodes — Claude
Desktop fires ``HarnessSessionEnded`` on transient signals (laptop
sleep, brief disconnect, idle timeout) and resumes the same
conversation under the same ``session_id``. The current-episode
boundary is first-class session state:
``harness_sessions.episode_started_at``, stamped by ``register_session``
on both fresh registration and reactivation (the moments that also emit
the ``HarnessSessionStarted`` / ``HarnessSessionResumed`` telemetry
markers). Pre-cutover sessions were backfilled from those
STATUS-severity ledger rows, so the column covers all history.

This module exposes one shared helper used by both
``events list --current-episode`` (via
:mod:`yoke_core.domain.events_queries` — the events *filter* is an
allowed telemetry query; only boundary resolution lives here) and
``who-claims --current-episode`` (via
:mod:`yoke_core.hooks.sessions_claims`). The contract is:

* Boundary = ``harness_sessions.episode_started_at``.
* When the session row is missing or carries no boundary the helper
  returns ``None``; callers MUST fail closed (return the empty set)
  rather than implicitly widen to "all events for the session".

Episode policy details and the orthogonal ``--current-episode`` flag
contract live in
``runtime/harness/claude/rules/session.md`` (Claude-only) and the
cross-harness decision record under
``docs/archive/decisions/session-resumption-policy.md``.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Sequence, Tuple

from .schema_common import _get_columns as _schema_get_columns


# Telemetry markers that accompany an episode boundary. Retained for
# audit prose; boundary RESOLUTION reads the session column, never these.
_BOUNDARY_EVENT_NAMES: Tuple[str, ...] = (
    "HarnessSessionResumed",
    "HarnessSessionStarted",
)


def resolve_current_episode_boundary(
    conn: Any,
    session_id: str,
) -> Optional[str]:
    """Return the ISO timestamp of the current episode boundary.

    Returns ``None`` when the session has no recorded boundary. Callers
    in the audit path fail closed on ``None`` so the filter never
    implicitly widens to "all events for the session".
    """
    if not session_id:
        return None
    try:
        columns = set(_schema_get_columns(conn, "harness_sessions"))
    except Exception:
        return None
    if "episode_started_at" not in columns:
        return None
    row = conn.execute(
        "SELECT episode_started_at FROM harness_sessions "
        "WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    value = row[0] if not hasattr(row, "keys") else row["episode_started_at"]
    return str(value) if value else None


def episode_boundary_event_names() -> Sequence[str]:
    """Return the boundary telemetry marker names (immutable tuple)."""
    return _BOUNDARY_EVENT_NAMES


def note_elided_prior_episodes(
    payload: Mapping[str, Any],
    where: str,
    params: Sequence[Any],
    result: MutableMapping[str, Any],
    db_path: Optional[str] = None,
) -> None:
    """Record how many rows the episode boundary hid from this same filter.

    An empty ``--current-episode`` answer is indistinguishable from
    "nothing happened" unless the query says what it left out, and a
    session that crossed a transient end/resume mid-work keeps its
    earlier evidence in the prior episode. That is not hypothetical: a
    close-out asked for this episode's guardrail denials four minutes
    after a sleep/resume cycle opened a new one, got nothing, and
    reported a clean run over seventeen real denials.

    Sets ``elided_prior_episode_rows`` on *result* only when the count is
    non-zero, so a genuinely quiet episode stays quiet. Never raises —
    an un-inspectable count must not fail the read it annotates.
    """
    if not payload.get("current_episode"):
        return
    from yoke_core.domain.events_queries import (
        EPISODE_BOUNDARY_CLAUSE,
        EPISODE_UNRESOLVED_CLAUSE,
    )

    if EPISODE_BOUNDARY_CLAUSE in where:
        # Same filter, same params — the boundary predicate inverted.
        prior = where.replace(EPISODE_BOUNDARY_CLAUSE, "created_at < %s", 1)
    elif EPISODE_UNRESOLVED_CLAUSE in where:
        # No boundary resolved, so the filter hid every row it matched.
        prior = where.replace(EPISODE_UNRESOLVED_CLAUSE, "1=1", 1)
    else:
        return
    try:
        from yoke_core.domain.db_helpers import connect

        conn = connect(db_path)
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM events {prior}", tuple(params),
            ).fetchone()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — an annotation never fails the read
        return
    count = int(row[0]) if row else 0
    if count:
        result["elided_prior_episode_rows"] = count


def claim_episode_scope(
    *,
    claim_claimed_at: Optional[str],
    boundary_created_at: Optional[str],
) -> str:
    """Classify an active claim against the current-episode boundary.

    Pure-Python helper used by ``who-claims --current-episode`` so the
    rendering callsite stays free of timestamp arithmetic. Returns one
    of ``"current_episode"`` (claim was acquired at or after the
    boundary), ``"inherited_from_prior_episode"`` (claim predates the
    boundary), or ``"unknown"`` (either timestamp is missing or
    unparseable).
    """
    if not claim_claimed_at or not boundary_created_at:
        return "unknown"
    try:
        return (
            "current_episode"
            if str(claim_claimed_at) >= str(boundary_created_at)
            else "inherited_from_prior_episode"
        )
    except TypeError:
        return "unknown"


__all__ = [
    "claim_episode_scope",
    "episode_boundary_event_names",
    "note_elided_prior_episodes",
    "resolve_current_episode_boundary",
]
