"""Auto-release active work-claims on the no-flags ``session-end`` path.

The no-flags ``end_session`` branch previously rejected with
``ACTIVE_CLAIM`` whenever the session still held work-claims, forcing
operators (and the ``/yoke do`` loop) to manually release each claim
before retrying. This helper centralises the inverse: enumerate the
session's active claims and release each through the typed work-claim
release path so item, epic_task, and process targets all use the same
semantics and process-owned linked path claims cascade through the
existing release behavior. Returns the JSON-safe per-claim release
payload that surfaces on the typed end-session response.

The destructive ``--release-claims`` path
(``handle_release_claims_branch``) remains
``sessions_lifecycle_destructive_guard``'s responsibility — this helper
is scoped to the deliberate no-flags CLI/operator path where the
session is being ended on purpose. On both branches the upstream
CHAIN_PENDING guard is the structural protection against ending a
session whose loop still has budget.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from .sessions_analytics import (
    EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
    SessionError,
)
from .sessions_lifecycle_release import (
    _POST_COMMIT_RECEIPT_KEY,
    release_work_claim_for_execution,
)
from .sessions_lifecycle_claim_release import emit_claim_release_post_commit
from .work_claim_targets import (
    WorkClaimTarget,
    from_row,
)


SESSION_ENDED_RELEASE_REASON = "session_ended"
NO_FLAGS_RELEASE_VIA = "no_flags"
AGENT_HANDOFF_RELEASE_VIA = "agent_handoff_session_scoped"


def _describe_target(target: WorkClaimTarget) -> Dict[str, Any]:
    """Render the kind-specific identifiers for the response payload."""
    return {"target_kind": target.kind, "scope": dict(target.scope)}


def _release_session_claim_rows(
    conn: Any,
    session_id: str,
    *,
    active_claim_rows,
    release_reason: str,
    commit: bool,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Release claim rows, optionally deferring their success telemetry."""
    released: List[Dict[str, Any]] = []
    post_commit_receipts: List[Dict[str, Any]] = []
    for row in active_claim_rows:
        target = from_row(dict(row))
        result = release_work_claim_for_execution(
            conn,
            session_id,
            target,
            release_reason,
            allow_non_terminal=True,
            commit=commit,
        )
        if not result.get("released"):
            if not commit:
                raise SessionError(
                    "CLAIM_RELEASE_FAILED",
                    f"Could not release locked claim {row['id']} while ending "
                    f"session '{session_id}'.",
                )
            continue
        entry = _describe_target(target)
        entry["claim_id"] = result["claim_id"]
        released.append(entry)
        receipt = result.get(_POST_COMMIT_RECEIPT_KEY)
        if receipt is not None:
            post_commit_receipts.append(receipt)
    return released, post_commit_receipts


def emit_session_claim_releases_post_commit(
    conn: Any,
    session_id: str,
    *,
    released: List[Dict[str, Any]],
    post_commit_receipts: List[Dict[str, Any]],
    release_reason: str = SESSION_ENDED_RELEASE_REASON,
    via: str = NO_FLAGS_RELEASE_VIA,
    emit_individual: bool = True,
) -> None:
    """Emit deferred per-claim and aggregate events after a batch commit."""
    if emit_individual:
        for receipt in post_commit_receipts:
            emit_claim_release_post_commit(conn, receipt)

    if released:
        first_item: Optional[str] = None
        for entry in released:
            scope = entry.get("scope") or {}
            if entry.get("target_kind") == "item" and scope.get("item_id") is not None:
                first_item = str(scope["item_id"])
                break
        _sa._emit_session_event(
            EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
            session_id=session_id,
            item_id=first_item,
            context={
                "released_count": len(released),
                "released_claims": released,
                "release_reason": release_reason,
                "via": via,
            },
        )


def release_session_claims_transactional(
    conn: Any,
    session_id: str,
    *,
    active_claim_rows,
    release_reason: str = SESSION_ENDED_RELEASE_REASON,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Stage all session claim releases in the caller-owned transaction."""
    return _release_session_claim_rows(
        conn,
        session_id,
        active_claim_rows=active_claim_rows,
        release_reason=release_reason,
        commit=False,
    )


def release_session_claims(
    conn: Any,
    session_id: str,
    *,
    active_claim_rows,
    release_reason: str = SESSION_ENDED_RELEASE_REASON,
    via: str = NO_FLAGS_RELEASE_VIA,
) -> List[Dict[str, Any]]:
    """Release each active work-claim and return the JSON-safe payload.

    Routes each release through :func:`release_work_claim_for_execution`
    with ``allow_non_terminal=True`` so process-owned path-claim cascade
    and target-kind semantics are consistent with every other claim
    release path. By default each typed release commits and emits success
    telemetry before the aggregate event.
    Session end uses :func:`release_session_claims_transactional` so every
    release, the terminal session row, and focus cleanup commit together.
    """
    released, post_commit_receipts = _release_session_claim_rows(
        conn,
        session_id,
        active_claim_rows=active_claim_rows,
        release_reason=release_reason,
        commit=True,
    )
    emit_session_claim_releases_post_commit(
        conn,
        session_id,
        released=released,
        post_commit_receipts=post_commit_receipts,
        release_reason=release_reason,
        via=via,
    )
    return released


__all__ = [
    "AGENT_HANDOFF_RELEASE_VIA",
    "NO_FLAGS_RELEASE_VIA",
    "SESSION_ENDED_RELEASE_REASON",
    "emit_session_claim_releases_post_commit",
    "release_session_claims",
    "release_session_claims_transactional",
]
