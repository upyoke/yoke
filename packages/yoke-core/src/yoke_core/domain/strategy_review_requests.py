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
    created = create_decision_request(
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
    withdraw_superseded_strategy_reviews(
        conn,
        project_id=int(project_id),
        slug=slug,
        revision=int(revision),
        session_id=session_id,
    )
    return created


def withdraw_superseded_strategy_reviews(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    revision: int,
    session_id: str = "",
) -> list[int]:
    """Release the reviews the new revision just made unanswerable.

    Every revision asks for its own review, so without this each edit leaves
    the previous ask pending on a revision nobody can act on any more.
    """
    from yoke_core.domain.decision_request_resolution import (
        withdraw_for_ended_subject,
    )
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "decision_requests"):
        return []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id, subject_key FROM decision_requests "
        "WHERE status = 'pending' AND kind = 'strategy_revision_review' "
        f"AND project_id = {marker} ORDER BY id",
        (int(project_id),),
    ).fetchall()
    withdrawn: list[int] = []
    for row in rows:
        parts = str(row[1]).split(":")
        if len(parts) < 3 or ":".join(parts[1:-1]) != slug:
            continue
        if not parts[-1].isdigit() or int(parts[-1]) >= int(revision):
            continue
        withdraw_for_ended_subject(
            conn,
            int(row[0]),
            reason=f"superseded by {slug} revision {int(revision)}",
            session_id=session_id,
        )
        withdrawn.append(int(row[0]))
    return withdrawn



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
    "withdraw_superseded_strategy_reviews",
]
