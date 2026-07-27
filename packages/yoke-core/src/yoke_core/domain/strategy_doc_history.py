"""Immutable strategy-document history reads, diffs, and restores."""

from __future__ import annotations

import difflib
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.strategy_docs import (
    StrategyDocConflictError,
    get_doc,
    next_updated_at,
    replace_conflict_teaching,
)
from yoke_core.domain.strategy_docs_schema import (
    STRATEGY_DOCS_TABLE,
    STRATEGY_DOC_REVISIONS_TABLE,
    record_doc_revision,
)


class StrategyDocRevisionMissingError(LookupError):
    """Raised when a requested immutable revision does not exist."""


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row(cursor: Any) -> Optional[dict[str, Any]]:
    value = cursor.fetchone()
    if value is None:
        return None
    if hasattr(value, "keys"):
        return dict(value)
    columns = [str(column[0]) for column in cursor.description]
    return dict(zip(columns, value))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(value) if hasattr(value, "keys") else dict(zip(columns, value))
        for value in cursor.fetchall()
    ]


def _operation_label(source_operation: str) -> str:
    operation = str(source_operation or "updated")
    family = operation.split(":", 1)[0]
    return {
        "create": "created",
        "ingest": "ingested",
        "replace": "replaced",
        "restore": "restored",
        "coordination_append": "updated",
    }.get(family, family.replace("_", " ").replace("-", " "))


def _is_title_only(slug: str, content: str) -> bool:
    lines = [line.strip() for line in str(content).splitlines() if line.strip()]
    return lines == [f"# {slug}"]


def _looks_like_implementation_plan(content: str) -> bool:
    headings = {
        line.removeprefix("## ").strip().casefold()
        for line in str(content).splitlines()
        if line.startswith("## ")
    }
    return "purpose" in headings and bool(
        headings.intersection({"decisions", "outcomes", "slices"})
    )


def _change_summary(
    *,
    slug: str,
    source_operation: str,
    content: str,
    previous_content: Optional[str],
) -> str:
    operation = str(source_operation or "updated")
    family, _, detail = operation.partition(":")
    if family == "create":
        return (
            "Initial title only"
            if _is_title_only(slug, content)
            else "Document created"
        )
    if family == "ingest":
        if (
            previous_content is not None
            and _is_title_only(slug, previous_content)
            and _looks_like_implementation_plan(content)
        ):
            return "Full implementation plan ingested"
        return "Document ingested"
    if family == "replace":
        return "Document replaced"
    if family == "restore":
        return f"Revision {detail} restored" if detail else "Revision restored"
    if family == "coordination_append":
        section = detail.replace("_", " ").strip()
        return f"{section.capitalize()} updated" if section else "Coordination updated"
    label = _operation_label(operation)
    return f"Document {label}" if label else "Document updated"


def list_doc_revisions(
    conn: Any,
    project_id: int,
    slug: str,
) -> list[dict[str, Any]]:
    """Return immutable snapshots newest first, without their full bodies."""
    get_doc(conn, project_id, slug)
    marker = _marker(conn)
    cursor = conn.execute(
        "SELECT revision, content, content_sha256, byte_length, source_operation, "
        "actor_id, session_id, created_at "
        f"FROM {STRATEGY_DOC_REVISIONS_TABLE} "
        f"WHERE project_id = {marker} AND slug = {marker} "
        "ORDER BY revision DESC",
        (int(project_id), slug),
    )
    revisions = _rows(cursor)
    for index, revision in enumerate(revisions):
        content = str(revision.pop("content"))
        previous_content = (
            str(revisions[index + 1]["content"]) if index + 1 < len(revisions) else None
        )
        revision["line_count"] = len(content.splitlines())
        revision["operation_label"] = _operation_label(
            str(revision["source_operation"])
        )
        revision["change_summary"] = _change_summary(
            slug=slug,
            source_operation=str(revision["source_operation"]),
            content=content,
            previous_content=previous_content,
        )
    return revisions


def get_doc_revision(
    conn: Any,
    project_id: int,
    slug: str,
    revision: int,
) -> dict[str, Any]:
    """Return one immutable revision snapshot including its body."""
    marker = _marker(conn)
    cursor = conn.execute(
        "SELECT revision, content, content_sha256, byte_length, "
        "source_operation, actor_id, session_id, created_at "
        f"FROM {STRATEGY_DOC_REVISIONS_TABLE} "
        f"WHERE project_id = {marker} AND slug = {marker} "
        f"AND revision = {marker}",
        (int(project_id), slug, int(revision)),
    )
    row = _row(cursor)
    if row is None:
        raise StrategyDocRevisionMissingError(
            f"strategy doc {slug!r} has no revision {revision}"
        )
    return row


def diff_doc_revisions(
    conn: Any,
    project_id: int,
    slug: str,
    from_revision: int,
    to_revision: int,
) -> dict[str, Any]:
    """Return a unified line diff between two immutable snapshots."""
    before = get_doc_revision(conn, project_id, slug, from_revision)
    after = get_doc_revision(conn, project_id, slug, to_revision)
    before_lines = str(before["content"]).splitlines(keepends=True)
    after_lines = str(after["content"]).splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"{slug}@{from_revision}",
            tofile=f"{slug}@{to_revision}",
        )
    )
    added = sum(
        1
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return {
        "slug": slug,
        "from_revision": int(from_revision),
        "to_revision": int(to_revision),
        "added_lines": added,
        "removed_lines": removed,
        "diff": diff,
    }


def restore_doc_revision(
    conn: Any,
    project_id: int,
    slug: str,
    revision: int,
    *,
    base_updated_at: str,
    actor_id: Optional[int],
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Restore old content by appending a new immutable revision."""
    current = get_doc(conn, project_id, slug)
    if current["updated_at"] != str(base_updated_at):
        raise StrategyDocConflictError(replace_conflict_teaching(slug))
    snapshot = get_doc_revision(conn, project_id, slug, revision)
    content = str(snapshot["content"])
    updated_at = next_updated_at()
    marker = _marker(conn)
    cursor = conn.execute(
        f"UPDATE {STRATEGY_DOCS_TABLE} "
        f"SET content = {marker}, updated_at = {marker}, "
        f"updated_by_actor_id = {marker} "
        f"WHERE project_id = {marker} AND slug = {marker} "
        f"AND updated_at = {marker}",
        (
            content,
            updated_at,
            actor_id,
            int(project_id),
            slug,
            str(base_updated_at),
        ),
    )
    if cursor.rowcount == 0:
        raise StrategyDocConflictError(replace_conflict_teaching(slug))
    new_revision = record_doc_revision(
        conn,
        int(project_id),
        slug,
        content,
        source_operation=f"restore:{int(revision)}",
        actor_id=actor_id,
        session_id=session_id,
        created_at=updated_at,
    )
    conn.commit()
    return {
        "slug": slug,
        "restored_revision": int(revision),
        "revision": new_revision,
        "updated_at": updated_at,
        "bytes": len(content.encode("utf-8")),
    }


__all__ = [
    "StrategyDocRevisionMissingError",
    "diff_doc_revisions",
    "get_doc_revision",
    "list_doc_revisions",
    "restore_doc_revision",
]
