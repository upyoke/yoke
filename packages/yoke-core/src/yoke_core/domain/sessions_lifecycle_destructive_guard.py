"""Claim-and-chain destructive-end guard for the SessionEnd path.

``end_session(release_claims=True)`` — the destructive branch invoked
by the SessionEnd hook — uses this guard to decide: when a session
signals it is ending, is the signal **transient** (chainable checkpoint
with budget remaining) or **permanent** (no chain to resume)?

Universal end policy: ``end_session`` releases claims directly when an
active claim of any kind is held; this guard fires only when no claims
remain and answers a single question — does the chain checkpoint still
have budget?

For a transient signal (chain pending) the destructive path is
deferred: a terminal session row is NOT written, and a
``HarnessSessionEndDeferred`` event records the decision. For a
permanent signal the destructive path runs as today. ``last_heartbeat``
is no longer consulted here — after the keepalive daemon was
eliminated it became a tool-activity recency signal rather than a
liveness signal, conflating idle-but-alive sessions with permanent
ends. ``last_heartbeat`` survives only for the 30-minute stale-session
reclaim sweep in ``yoke_core.domain.sessions_cleanup``.

Not the same path as ``end_session_if_empty``. ``end_session_if_empty``
is a separate non-destructive idle-cleanup helper used by the Stop hook
and the routed loop: it checks claim/chain state directly and either
closes the session (``ended``), defers with structured status
(``has_claims`` / ``chain_pending``), or no-ops
(``already_ended`` / ``not_found``). It does NOT call
``evaluate_destructive_end`` because it never releases claims — the
destructive guard is specifically about the SessionEnd
``--release-claims`` branch where the destructive write would otherwise
discard live ownership state on a transient signal.

The guard is intentionally narrow: it consults SQLite-visible state
only (the persisted chain checkpoint inside ``offer_envelope``). It
does not call back into the hook runner or any harness substrate, so
the same function is safe to import from the API domain and from the
harness lifecycle dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import db_backend
from .runtime_settings import get_seconds
from .sessions_queries import _now_iso
from .sessions_render_end_chain_pending import chain_pending_state


# Default reacquire window matches machine config
# session_reactivation_reacquire_window_s — the canonical window we extend
# heartbeats by on the defer path so concurrent scheduler sweeps in another
# session see fresh claims for the duration of the reacquire window.
DEFAULT_REACQUIRE_WINDOW_S = 300


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class AgentPresenceEvidence:
    """Structured presence signal recorded on lifecycle events."""

    chain_budget_remaining: bool
    chain_override_authorized: bool = False

    def as_dict(self) -> dict:
        return {
            "chain_budget_remaining": self.chain_budget_remaining,
            "chain_override_authorized": self.chain_override_authorized,
        }


@dataclass(frozen=True)
class DestructiveEndDecision:
    """Outcome of the chain-aware destructive-end check."""

    defer: bool
    reason: str  # "chain_pending" / "permanent"
    evidence: AgentPresenceEvidence


def resolve_reacquire_window_s(*, override_s: Optional[int] = None) -> int:
    """Resolve the reacquire window from config or an explicit override.

    Used on the defer-end path to advance ``last_heartbeat`` on every
    active claim held by the deferring session, so another session's
    scheduler sweep sees a fresh heartbeat for the duration of the
    resume window and will not reclaim the deferred session's work
    mid-pause.
    """
    if override_s is not None and override_s > 0:
        return int(override_s)
    return get_seconds(
        "session_reactivation_reacquire_window_s",
        DEFAULT_REACQUIRE_WINDOW_S,
    )


def _advance_iso(seconds_ahead: int) -> str:
    """Return an ISO-8601 UTC timestamp ``seconds_ahead`` seconds from now.

    The defer-branch heartbeat refresh forward-stamps
    ``work_claims.last_heartbeat`` to ``now + reacquire_window`` so the
    canonical stale-TTL math (``now - last_heartbeat > ttl``) yields a
    negative value for the configured window, neutralising concurrent
    scheduler sweeps during the resume protection period.
    """
    now_dt = datetime.fromisoformat(_now_iso().replace("Z", "+00:00"))
    advanced = now_dt + timedelta(seconds=int(seconds_ahead))
    return advanced.isoformat(timespec="microseconds").replace("+00:00", "Z")


def refresh_deferred_session_claim_heartbeats(
    conn: Any,
    session_id: str,
    *,
    reacquire_window_s: Optional[int] = None,
) -> int:
    """Forward-stamp ``last_heartbeat`` on the deferring session's claims.

    Bumps every active (``released_at IS NULL``) ``work_claims`` row owned
    by ``session_id`` to ``now + reacquire_window_s``. Strict same-session
    filter — other sessions' claims are untouched, released rows are
    untouched. Returns the number of rows updated. Called from the
    defer branch of :func:`handle_release_claims_branch` so the window
    of protection that the reactivation path expects (default 300s) is
    in place before another session's stale-claim sweep runs.

    Forward-stamping past wall-clock NOW is intentional per the spec's
    Watch Out For #4. A subsequent live heartbeat (via a PreToolUse
    refresh after the session resumes) overwrites the future value with
    ``NOW`` — the protection is needed only while the harness runtime is
    paused, so live activity correctly relaxes back to normal stale-TTL
    math.
    """
    window = resolve_reacquire_window_s(override_s=reacquire_window_s)
    future_ts = _advance_iso(window)
    p = _p(conn)
    cursor = conn.execute(
        f"UPDATE work_claims SET last_heartbeat = {p} "
        f"WHERE session_id = {p} AND released_at IS NULL",
        (future_ts, session_id),
    )
    conn.commit()
    return cursor.rowcount or 0


def evaluate_destructive_end(
    conn: Any,
    session_id: str,
    *,
    chain_override_authorized: bool = False,
) -> DestructiveEndDecision:
    """Decide whether a destructive end should be deferred for this session.

    ``defer=True`` when the persisted chain checkpoint is chainable with
    remaining budget — the routed loop intentionally released its claim
    mid-chain and the next turn must be able to resume.

    ``defer=False`` otherwise; that is the permanent end case and the
    caller falls through to the destructive path.

    When ``chain_override_authorized`` is True, the chain-pending branch
    is skipped and the chain budget is treated as waived for this
    decision.
    """
    state = chain_pending_state(conn, session_id)
    chain_pending = bool(state.pending)

    if chain_pending and not chain_override_authorized:
        return DestructiveEndDecision(
            defer=True,
            reason="chain_pending",
            evidence=AgentPresenceEvidence(
                chain_budget_remaining=True,
                chain_override_authorized=False,
            ),
        )
    return DestructiveEndDecision(
        defer=False,
        reason="permanent",
        evidence=AgentPresenceEvidence(
            chain_budget_remaining=chain_pending,
            chain_override_authorized=chain_override_authorized,
        ),
    )


def _format_claim_details(active_claim_rows) -> list[dict]:
    """Materialise the JSON-safe claim detail rows the lifecycle events carry."""
    return [
        {
            "claim_id": r["id"],
            "item_id": str(r["item_id"]) if r["item_id"] is not None else None,
            "task_num": r["task_num"],
        }
        for r in active_claim_rows
    ]


def handle_release_claims_branch(
    conn: Any,
    session_id: str,
    *,
    force: bool,
    active_claim_rows,
    chain_override_authorized: bool = False,
):
    """Decide and act on the SessionEnd ``release_claims=True`` branch.

    Returns a tuple ``(deferred, evidence_dict)``:

    * ``deferred=True`` means the destructive guard refused this signal
      as transient — the caller MUST return the session row early
      without writing ``ended_at`` or emitting ``HarnessSessionEnded``.
      Claims stay active; a ``HarnessSessionEndDeferred`` event has
      already been recorded.
    * ``deferred=False`` means the destructive path runs: all claims
      have been released, ``HarnessSessionEndReleasedClaims`` has been
      emitted, and the caller continues with the normal session-end
      commit + ``HarnessSessionEnded`` emission.

    The ``evidence_dict`` is the agent_presence_evidence payload from
    the guard and is suitable for inclusion on the
    ``HarnessSessionEnded`` envelope.
    """
    from . import sessions_analytics as _sa
    from .sessions_analytics import EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
    from .scheduler_events import emit_harness_session_end_deferred
    from .sessions_lifecycle_release import release_all_claims

    claim_details = _format_claim_details(active_claim_rows)
    decision = evaluate_destructive_end(
        conn,
        session_id,
        chain_override_authorized=chain_override_authorized,
    )
    if decision.defer:
        # Forward-stamp last_heartbeat on the deferring session's active
        # claims so concurrent scheduler sweeps in OTHER sessions do not
        # reclaim during the resume protection window. The destructive
        # guard's defer signal is the explicit moment we extend
        # protection — see ``refresh_deferred_session_claim_heartbeats``.
        refresh_deferred_session_claim_heartbeats(conn, session_id)
        first_item = (
            str(active_claim_rows[0]["item_id"])
            if active_claim_rows[0]["item_id"] is not None
            else None
        )
        emit_harness_session_end_deferred(
            session_id=session_id,
            defer_reason=decision.reason,
            agent_presence_evidence=decision.evidence.as_dict(),
            active_claim_count=len(active_claim_rows),
            claim_details=claim_details,
            item_id=first_item,
        )
        return True, decision.evidence.as_dict()

    released_count = release_all_claims(
        conn, session_id, reason="session_ended",
    )
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
        session_id=session_id,
        context={
            "released_count": released_count,
            "claim_details": claim_details,
            "force": force,
            "agent_presence_evidence": decision.evidence.as_dict(),
        },
    )
    return False, decision.evidence.as_dict()


__all__ = [
    "AgentPresenceEvidence",
    "DEFAULT_REACQUIRE_WINDOW_S",
    "DestructiveEndDecision",
    "evaluate_destructive_end",
    "handle_release_claims_branch",
    "refresh_deferred_session_claim_heartbeats",
    "resolve_reacquire_window_s",
]
