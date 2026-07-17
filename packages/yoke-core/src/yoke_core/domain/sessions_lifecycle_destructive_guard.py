"""Claim-release branch of the destructive session-end path.

``end_session(release_claims=True)`` — the destructive branch reached
only by explicit session-end calls (CLI/operator; the Stop and
SessionEnd hooks route through the non-destructive
``end_session_if_empty`` instead) — releases active claims through this
module. It runs only when the session still holds active claims; the
claim-free path in ``sessions_render_end`` never reaches it.

Chain protection lives upstream: ``end_session`` fails closed with
``CHAIN_PENDING`` while a chainable checkpoint still has budget, unless
the caller supplies ``override_chain_end=True`` plus a non-empty
rationale. By the time this branch runs, the chain gate has either
passed (no budget remaining) or been explicitly overridden; the release
always proceeds, and the structured ``agent_presence_evidence`` payload
records which of those it was on the terminal events.

``last_heartbeat`` is not consulted here — after the keepalive daemon
was eliminated it became a tool-activity recency signal rather than a
liveness signal, conflating idle-but-alive sessions with permanent
ends. It survives only for the stale-session reclaim sweep in
``yoke_core.domain.sessions_cleanup`` (TTL from the
``session_stale_ttl_minutes`` machine-config key).

Not the same path as ``end_session_if_empty``. ``end_session_if_empty``
is a separate non-destructive idle-cleanup helper used by the Stop and
SessionEnd hooks: it checks claim/chain state directly and either
closes the session (``ended``), reports structured skip status
(``has_claims`` / ``chain_pending``), or no-ops
(``already_ended`` / ``not_found``). It never releases claims.

This module is intentionally narrow: it consults DB-visible state only
(the persisted chain checkpoint inside ``offer_envelope``). It does not
call back into the hook runner or any harness substrate, so the same
function is safe to import from the API domain and from the harness
lifecycle dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .sessions_render_end_chain_pending import chain_pending_state


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


def evaluate_destructive_end(
    conn: Any,
    session_id: str,
    *,
    chain_override_authorized: bool = False,
) -> AgentPresenceEvidence:
    """Build the agent-presence evidence for a destructive end.

    The upstream CHAIN_PENDING gate in ``end_session`` has already
    refused any chain-pending session without an authorized override,
    so ``chain_budget_remaining=True`` here always pairs with
    ``chain_override_authorized=True``.
    """
    state = chain_pending_state(conn, session_id)
    return AgentPresenceEvidence(
        chain_budget_remaining=bool(state.pending),
        chain_override_authorized=chain_override_authorized,
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
) -> dict:
    """Release all claims on the session-end ``release_claims=True`` branch.

    Releases every active claim with ``release_reason='session_ended'``,
    emits ``HarnessSessionEndReleasedClaims``, and returns the
    agent_presence_evidence payload for inclusion on the
    ``HarnessSessionEnded`` envelope.
    """
    from . import sessions_analytics as _sa
    from .sessions_analytics import EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
    from .sessions_lifecycle_release import release_all_claims

    claim_details = _format_claim_details(active_claim_rows)
    evidence = evaluate_destructive_end(
        conn,
        session_id,
        chain_override_authorized=chain_override_authorized,
    )
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
            "agent_presence_evidence": evidence.as_dict(),
        },
    )
    return evidence.as_dict()


__all__ = [
    "AgentPresenceEvidence",
    "evaluate_destructive_end",
    "handle_release_claims_branch",
]
