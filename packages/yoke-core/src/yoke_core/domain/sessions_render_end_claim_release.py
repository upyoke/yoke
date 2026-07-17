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
from .sessions_analytics import EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
from .sessions_lifecycle_release import release_work_claim_for_execution
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
    from_row,
)


SESSION_ENDED_RELEASE_REASON = "session_ended"
NO_FLAGS_RELEASE_VIA = "no_flags"
AGENT_HANDOFF_RELEASE_VIA = "agent_handoff_session_scoped"


def _describe_target(target: WorkClaimTarget) -> Dict[str, Any]:
    """Render the kind-specific identifiers for the response payload."""
    desc: Dict[str, Any] = {"target_kind": target.kind}
    if target.kind == TARGET_KIND_ITEM:
        desc["item_id"] = target.item_id
    elif target.kind == TARGET_KIND_EPIC_TASK:
        desc["epic_id"] = target.epic_id
        desc["task_num"] = target.task_num
    elif target.kind == TARGET_KIND_PROCESS:
        desc["process_key"] = target.process_key
        desc["conflict_group"] = target.conflict_group
    return desc


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
    release path. Emits one aggregate
    ``HarnessSessionEndReleasedClaims`` event covering the release
    outcome — mirrors the destructive-guard branch so audit callers find
    session-end claim releases under one canonical event name regardless
    of which session-end branch ran.

    ``release_reason`` defaults to ``"session_ended"`` (the no-flags
    ``end_session`` path). The session-scoped agent-handoff primitive
    (:mod:`claims_work_release_session_scoped`) passes
    ``"agent_handoff_session_scoped"`` so the event's
    ``release_reason_intent`` distinguishes operator intent without
    breaking the schema-enum ``work_claims.release_reason`` (the
    schema-enum value is the canonicalized mapping handled inside
    :func:`release_work_claim_for_execution`). ``via`` matches the
    aggregate event's ``context.via`` field for the same audit purpose.

    Returns one entry per released claim with stable JSON-safe keys:
    ``claim_id``, ``target_kind``, and the target-kind identifiers
    (``item_id`` / ``epic_id`` + ``task_num`` / ``process_key`` +
    ``conflict_group``). Released claims are returned in their input
    order so callers can correlate against ``active_claim_rows``.

    A release that returns ``released=False`` (the typed path already
    emitted ``ItemClaimReleaseFailed`` for audit) is omitted from the
    return list — a single failing release does not strand the others.
    """
    released: List[Dict[str, Any]] = []
    for row in active_claim_rows:
        target = from_row({
            "target_kind": row["target_kind"],
            "item_id": row["item_id"],
            "epic_id": row["epic_id"],
            "task_num": row["task_num"],
            "process_key": row["process_key"],
            "conflict_group": row["conflict_group"],
        })
        result = release_work_claim_for_execution(
            conn,
            session_id,
            target,
            release_reason,
            allow_non_terminal=True,
        )
        if not result.get("released"):
            continue
        entry = _describe_target(target)
        entry["claim_id"] = result["claim_id"]
        released.append(entry)

    if released:
        first_item: Optional[str] = None
        for entry in released:
            if entry.get("item_id") is not None:
                first_item = str(entry["item_id"])
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

    return released


__all__ = [
    "AGENT_HANDOFF_RELEASE_VIA",
    "NO_FLAGS_RELEASE_VIA",
    "SESSION_ENDED_RELEASE_REASON",
    "release_session_claims",
]
