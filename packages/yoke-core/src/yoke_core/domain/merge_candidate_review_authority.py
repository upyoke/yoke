"""Who may clear a merge candidate, and who may stop it needing clearance.

Authority for an ordinary decision request is the ACTOR's role. That is not
enough here, and the difference is the whole point of this gate: on a
workstation every agent carries the operator's own actor, so an actor-only
rule lets the worker whose branch is waiting approve its own candidate and
merge -- the gate holds nothing it was built to hold.

So this kind binds authority to the SESSION instead:

* the session holding the item's work claim may never clear it, whatever
  actor it carries -- it is the party under review;
* a session holding a live steering seat that covers the item may;
* a resolution carrying no harness session at all is a person acting
  through the web Inbox, and a human actor there may.

The same rule guards the posture key, because "this item needs no review"
is the same decision as "this candidate is cleared", reached by removing
the question instead of answering it.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.actors import is_human_actor
from yoke_core.domain.steering_scope_coverage import covering_claims
from yoke_core.domain.steering_scope_membership import item_coverage_target

SELF_CLEARANCE_CODE = "merge_candidate_review_self_clearance"
UNAUTHORIZED_CODE = "merge_candidate_review_unauthorized"

_RECOVERY = (
    "A candidate is cleared by the steering seat covering the item "
    "(`yoke claims steering list --project <id> --active-only` names it), "
    "or by a person answering it in the web Inbox. Report the request id "
    "upward and let that seat answer."
)


class MergeCandidateReviewAuthorityError(PermissionError):
    """The caller may not clear this candidate, or relax its requirement."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _work_claim_session(conn: Any, item_id: int) -> str:
    """The session holding this item, or empty when none is recorded.

    A schema with no claim table answers empty and stays safe: the same
    absence leaves every seat unreadable too, so a session caller is
    refused for holding no seat rather than admitted for holding no claim.
    """
    from yoke_core.domain.schema_common import _table_exists
    from yoke_core.domain.sessions_queries_lookup import get_claim_for_work_unit

    if not _table_exists(conn, "work_claims"):
        return ""
    row = get_claim_for_work_unit(conn, item_id=str(int(item_id)))
    return str((row or {}).get("session_id") or "")


def _project_id(conn: Any, item_id: int) -> Optional[int]:
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    value = row["project_id"] if hasattr(row, "keys") else row[0]
    return int(value) if value is not None else None


def _seat_covers(conn: Any, *, item_id: int, session_id: str) -> bool:
    project_id = _project_id(conn, int(item_id))
    if project_id is None:
        return False
    target = item_coverage_target(
        conn, project_id=int(project_id), item_id=int(item_id)
    )
    return any(
        str(claim["session_id"]) == str(session_id)
        for claim in covering_claims(conn, target)
    )


def require_clearance_authority(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    actor_id: Optional[int],
    action: str,
) -> None:
    """Raise unless this caller may take ``action`` on the item's review."""
    caller = str(session_id or "").strip()
    holder = _work_claim_session(conn, int(item_id))
    if caller and holder and caller == holder:
        raise MergeCandidateReviewAuthorityError(
            SELF_CLEARANCE_CODE,
            f"{SELF_CLEARANCE_CODE}: this session holds the item's work "
            f"claim, so it may not {action}. A candidate review exists to "
            "put a second party between the branch and the base branch, and "
            "the actor a worker carries is the operator's own -- only the "
            f"session tells them apart. {_RECOVERY}",
        )
    if not caller:
        if actor_id is not None and is_human_actor(conn, int(actor_id)):
            return
        raise MergeCandidateReviewAuthorityError(
            UNAUTHORIZED_CODE,
            f"{UNAUTHORIZED_CODE}: a call carrying no harness session may "
            f"{action} only as a person acting through the web Inbox, and "
            f"this one carries no human actor. {_RECOVERY}",
        )
    if _seat_covers(conn, item_id=int(item_id), session_id=caller):
        return
    raise MergeCandidateReviewAuthorityError(
        UNAUTHORIZED_CODE,
        f"{UNAUTHORIZED_CODE}: session {caller} holds no live steering seat "
        f"covering this item, so it may not {action}. {_RECOVERY}",
    )


__all__ = [
    "MergeCandidateReviewAuthorityError",
    "SELF_CLEARANCE_CODE",
    "UNAUTHORIZED_CODE",
    "require_clearance_authority",
]
