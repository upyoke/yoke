"""Review projections and ancestry for strategy documents and Blitzes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain.actor_render import actor_render_label
from yoke_core.domain.decision_requests import list_subject_requests
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.strategy_doc_history import list_doc_revisions
from yoke_core.domain.strategy_doc_presentation import summary_from_row
from yoke_core.domain.strategy_docs import (
    StrategyDocMissingError,
    get_doc,
    project_doc_slugs,
)
from yoke_core.domain.strategy_execution import (
    StrategyExecutionLinkError,
    _active_item_claim,
    _marker,
    _require_blitz_item,
    _row,
    active_strategy_doc_claim,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def set_strategy_doc_parent(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    parent_slug: Optional[str],
) -> dict[str, Any]:
    """Set or clear the single same-project parent without forming a cycle."""
    get_doc(conn, int(project_id), slug)
    clean_parent = str(parent_slug or "").strip() or None
    if clean_parent == slug:
        raise StrategyExecutionLinkError("a strategy document cannot parent itself")
    marker = _marker(conn)
    cursor = clean_parent
    visited = {slug}
    while cursor is not None:
        if cursor in visited:
            raise StrategyExecutionLinkError("strategy ancestry cannot form a cycle")
        visited.add(cursor)
        row = _row(conn.execute(
            "SELECT parent_slug FROM strategy_docs "
            f"WHERE project_id = {marker} AND slug = {marker}",
            (int(project_id), cursor),
        ))
        if row is None:
            raise StrategyDocMissingError(
                f"project {project_id} has no strategy doc {cursor!r}"
            )
        cursor = (
            str(row["parent_slug"]) if row["parent_slug"] is not None else None
        )
    conn.execute(
        f"UPDATE strategy_docs SET parent_slug = {marker} "
        f"WHERE project_id = {marker} AND slug = {marker}",
        (clean_parent, int(project_id), slug),
    )
    conn.commit()
    return {"slug": slug, "parent_slug": clean_parent}


def list_strategy_surfaces(conn: Any, project_id: int) -> list[dict[str, Any]]:
    """Return the corpus with ancestry, revision, and execution facts."""
    marker = _marker(conn)
    recent_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    rows = conn.execute(
        "SELECT d.slug, d.content, d.updated_at, d.updated_by_actor_id, "
        "d.archived_at, d.parent_slug, "
        "(SELECT COUNT(*) FROM strategy_doc_revisions r "
        " WHERE r.project_id = d.project_id AND r.slug = d.slug) AS revisions, "
        "(SELECT COUNT(*) FROM strategy_doc_revisions r "
        " WHERE r.project_id = d.project_id AND r.slug = d.slug "
        f" AND r.created_at >= {marker}) AS recent_writes, "
        "c.owner_kind AS execution_owner_kind, "
        "c.owner_session_id AS execution_owner_session_id, "
        "c.owner_item_id AS execution_item_id, i.title AS execution_item_title, "
        "i.project_sequence AS execution_item_sequence, "
        "p.slug AS project_slug, p.public_item_prefix "
        "FROM strategy_docs d "
        "JOIN projects p ON p.id = d.project_id "
        "LEFT JOIN strategy_doc_claims c "
        " ON c.project_id = d.project_id "
        "AND c.strategy_doc_slug = d.slug AND c.released_at IS NULL "
        "LEFT JOIN items i ON i.id = c.owner_item_id "
        f"WHERE d.project_id = {marker}",
        (recent_cutoff, int(project_id)),
    ).fetchall()
    order = {
        slug: index for index, slug in enumerate(
            project_doc_slugs(conn, int(project_id)),
        )
    }
    result = []
    for row in rows:
        values = dict(row)
        summary = summary_from_row(conn, values)
        held = values["execution_owner_kind"] is not None
        summary.update({
            "parent_slug": values["parent_slug"],
            "revisions": int(values["revisions"]),
            "recent_writes": int(values["recent_writes"]),
            "execution_owner_kind": values["execution_owner_kind"],
            "execution_owner_session_id": values["execution_owner_session_id"],
            "execution_item_id": values["execution_item_id"],
            "execution_item_title": values["execution_item_title"],
            "execution_item_ref": (
                format_item_ref(
                    values["project_slug"],
                    values["public_item_prefix"],
                    values["execution_item_sequence"],
                    item_id=int(values["execution_item_id"]),
                )
                if values["execution_item_id"] is not None else None
            ),
            "execution_state": (
                "claimed" if held
                else ("reference" if values["archived_at"] is not None else "available")
            ),
        })
        result.append(summary)
    result.sort(key=lambda doc: order[str(doc["slug"])])
    return result


def strategy_write_activity(
    conn: Any,
    project_id: int,
    *,
    days: int = 120,
) -> list[dict[str, Any]]:
    """Return real per-day revision counts for the corpus activity sparkline."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max(int(days), 1) - 1)
    ).strftime("%Y-%m-%d")
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT SUBSTRING(created_at, 1, 10) AS day, COUNT(*) AS writes "
        "FROM strategy_doc_revisions "
        f"WHERE project_id = {marker} AND created_at >= {marker} "
        "GROUP BY SUBSTRING(created_at, 1, 10) ORDER BY day",
        (int(project_id), cutoff),
    ).fetchall()
    return [
        {"day": str(row["day"]), "writes": int(row["writes"])}
        for row in rows
    ]


def get_strategy_surface(
    conn: Any,
    project_id: int,
    slug: str,
) -> dict[str, Any]:
    """Return the document, history, ancestry, references, and claim facts."""
    doc = get_doc(conn, int(project_id), slug)
    marker = _marker(conn)
    meta = _row(conn.execute(
        "SELECT parent_slug FROM strategy_docs "
        f"WHERE project_id = {marker} AND slug = {marker}",
        (int(project_id), slug),
    )) or {}
    claim = active_strategy_doc_claim(
        conn, project_id=int(project_id), slug=slug,
    )
    corpus = project_doc_slugs(conn, int(project_id))
    references = [
        candidate for candidate in corpus
        if candidate != slug and re.search(
            rf"(?<![A-Z0-9_-]){re.escape(candidate)}(?![A-Z0-9_-])",
            doc["content"],
        )
    ]
    revisions = list_doc_revisions(conn, int(project_id), slug)
    current_revision = int(revisions[0]["revision"]) if revisions else None
    review_requests = (
        list_subject_requests(
            conn,
            "strategy_doc_revision",
            f"{int(project_id)}:{slug}:{current_revision}",
        )
        if current_revision is not None else []
    )
    return {
        **doc,
        "updated_by": actor_render_label(conn, doc["updated_by_actor_id"]),
        "bytes": len(doc["content"].encode("utf-8")),
        "parent_slug": meta.get("parent_slug"),
        "references": references,
        "revisions": revisions,
        "current_revision": current_revision,
        "review_requests": review_requests,
        "pending_review_count": sum(
            1 for request in review_requests if request["status"] == "pending"
        ),
        "execution_claim": claim,
    }


def get_blitz_surface(conn: Any, item_id: int) -> dict[str, Any]:
    """Return the thin Blitz shell entirely from persisted system facts."""
    item = _require_blitz_item(conn, item_id)
    runtime = load_item_workflow_runtime(conn, int(item_id))
    marker = _marker(conn)
    link = _row(conn.execute(
        "SELECT project_id, strategy_doc_slug, linked_at "
        "FROM item_strategy_docs "
        f"WHERE item_id = {marker}",
        (int(item_id),),
    ))
    item_claim = _active_item_claim(conn, int(item_id))
    doc = (
        get_strategy_surface(
            conn, int(link["project_id"]), str(link["strategy_doc_slug"]),
        )
        if link is not None else None
    )
    return {
        "item": item,
        "workflow_version": runtime.version,
        "workflow_policies": dict(runtime.policies),
        "execution_document": doc,
        "execution_linked_at": link["linked_at"] if link else None,
        "item_claim": item_claim,
        "worktree_lanes": list_item_worktrees(
            conn, int(item_id), active_only=False,
        ),
    }


__all__ = [
    "get_blitz_surface",
    "get_strategy_surface",
    "list_strategy_surfaces",
    "set_strategy_doc_parent",
    "strategy_write_activity",
]
