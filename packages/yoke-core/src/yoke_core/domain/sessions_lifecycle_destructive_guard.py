"""Evidence and claim-release events for explicit destructive session ending."""

from __future__ import annotations

from typing import Any

from .work_claim_targets import from_row as target_from_row


def _format_claim_details(active_claim_rows) -> list[dict]:
    """Materialise the JSON-safe claim detail rows the lifecycle events carry."""
    details: list[dict] = []
    for row in active_claim_rows:
        target = target_from_row(row)
        item_id = target.item_id if target.item_id is not None else target.epic_id
        details.append(
            {
                "claim_id": row["id"],
                "item_id": str(item_id) if item_id is not None else None,
                "task_num": target.task_num,
            }
        )
    return details


def prepare_release_claims_branch(
    conn: Any,
    session_id: str,
    *,
    force: bool,
    active_claim_rows,
) -> tuple[dict, dict]:
    """Build evidence and event context without releasing or emitting."""
    evidence = {"explicit_claim_release": True}
    return evidence, {
        "claim_details": _format_claim_details(active_claim_rows),
        "force": force,
        "agent_presence_evidence": evidence,
    }


def emit_release_claims_branch_event(
    session_id: str,
    *,
    released_count: int,
    context: dict,
) -> None:
    """Emit the destructive release aggregate after its transaction commits."""
    from . import sessions_analytics as _sa
    from .sessions_analytics import EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS

    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
        session_id=session_id,
        context={"released_count": released_count, **context},
    )


def handle_release_claims_branch(
    conn: Any,
    session_id: str,
    *,
    force: bool,
    active_claim_rows,
) -> dict:
    """Release all claims on the session-end ``release_claims=True`` branch.

    Releases every active claim with ``release_reason='session_ended'``,
    emits ``HarnessSessionEndReleasedClaims``, and returns the
    agent_presence_evidence payload for inclusion on the
    ``HarnessSessionEnded`` envelope.
    """
    from .sessions_lifecycle_release import release_all_claims

    evidence, event_context = prepare_release_claims_branch(
        conn,
        session_id,
        force=force,
        active_claim_rows=active_claim_rows,
    )
    released_count = release_all_claims(
        conn,
        session_id,
        reason="session_ended",
    )
    emit_release_claims_branch_event(
        session_id,
        released_count=released_count,
        context=event_context,
    )
    return evidence


__all__ = [
    "emit_release_claims_branch_event",
    "handle_release_claims_branch",
    "prepare_release_claims_branch",
]
