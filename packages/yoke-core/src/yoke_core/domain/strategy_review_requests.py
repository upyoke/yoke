"""Decision-request producer for immutable strategy-document revisions."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
)


def ensure_strategy_revision_review(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    revision: int,
    originator_actor_id: Optional[int],
    reviewer_actor_id: Optional[int] = None,
    session_id: str = "",
) -> tuple[dict[str, Any], bool]:
    """Create or reuse a nonblocking review request for one revision."""
    actor_id = originator_actor_id
    if actor_id is not None:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        exists = conn.execute(
            f"SELECT 1 FROM actors WHERE id = {marker}", (int(actor_id),),
        ).fetchone()
        if exists is None:
            actor_id = None
    named_actor_ids: list[int] = []
    if reviewer_actor_id is not None:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        reviewer = conn.execute(
            f"SELECT 1 FROM actors WHERE id = {marker}",
            (int(reviewer_actor_id),),
        ).fetchone()
        if reviewer is None:
            raise LookupError(f"reviewer actor {reviewer_actor_id} does not exist")
        named_actor_ids.append(int(reviewer_actor_id))
    return create_decision_request(
        conn,
        kind="strategy_revision_review",
        subject_type="strategy_doc_revision",
        subject_key=f"{int(project_id)}:{slug}:{int(revision)}",
        project_id=int(project_id),
        originator_actor_id=actor_id,
        role_authorities=[
            RoleAuthority("project", int(project_id), "owner"),
            RoleAuthority("project", int(project_id), "operator"),
        ],
        named_actor_ids=named_actor_ids,
        subject_context={
            "slug": slug,
            "revision": int(revision),
            "title": f"{slug} — review revision {int(revision)}",
        },
        session_id=session_id,
    )


def ensure_current_strategy_revision_review(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    originator_actor_id: Optional[int],
    reviewer_actor_id: Optional[int] = None,
    session_id: str = "",
) -> tuple[dict[str, Any], bool]:
    """Resolve the current immutable revision, then request its review."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT MAX(revision) FROM strategy_doc_revisions "
        f"WHERE project_id = {marker} AND slug = {marker}",
        (int(project_id), slug),
    ).fetchone()
    if row is None or row[0] is None:
        raise LookupError(f"strategy doc {slug!r} has no immutable revision")
    return ensure_strategy_revision_review(
        conn,
        project_id=project_id,
        slug=slug,
        revision=int(row[0]),
        originator_actor_id=originator_actor_id,
        reviewer_actor_id=reviewer_actor_id,
        session_id=session_id,
    )


__all__ = [
    "ensure_current_strategy_revision_review",
    "ensure_strategy_revision_review",
]
