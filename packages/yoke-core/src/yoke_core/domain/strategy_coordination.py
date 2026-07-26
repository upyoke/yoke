"""Append-only coordination writes and Blitz completion evidence checks."""

from __future__ import annotations

import re
from typing import Any, Optional

from yoke_core.domain.strategy_docs import (
    StrategyDocMissingError,
    next_updated_at,
)
from yoke_core.domain.strategy_docs_schema import (
    STRATEGY_DOCS_TABLE,
    record_doc_revision,
)
from yoke_core.domain.strategy_execution import _marker, _row

COORDINATION_SECTIONS = frozenset({"Slice Log", "Live Status"})


def _append_to_markdown_section(
    content: str,
    section: str,
    entry: str,
) -> str:
    lines = content.rstrip().splitlines()
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    target_index = None
    target_level = 2
    for index, line in enumerate(lines):
        match = heading_pattern.match(line)
        if match and match.group(2).strip().casefold() == section.casefold():
            target_index = index
            target_level = len(match.group(1))
            break
    entry_lines = entry.strip().splitlines()
    if target_index is None:
        return "\n".join([
            *lines,
            "",
            f"## {section}",
            "",
            *entry_lines,
            "",
        ])
    insert_at = len(lines)
    for index in range(target_index + 1, len(lines)):
        match = heading_pattern.match(lines[index])
        if match and len(match.group(1)) <= target_level:
            insert_at = index
            break
    prefix = lines[:insert_at]
    suffix = lines[insert_at:]
    while prefix and not prefix[-1].strip():
        prefix.pop()
    return "\n".join([
        *prefix,
        "",
        *entry_lines,
        "",
        *suffix,
    ]).rstrip() + "\n"


def append_strategy_coordination(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    section: str,
    entry: str,
    actor_id: Optional[int],
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Append a log entry without granting revision authority over the plan."""
    clean_section = str(section).strip()
    if clean_section not in COORDINATION_SECTIONS:
        raise ValueError(
            f"coordination section must be one of {sorted(COORDINATION_SECTIONS)}"
        )
    clean_entry = str(entry).strip()
    if not clean_entry:
        raise ValueError("coordination entry must be non-empty")
    if any(re.match(r"^\s*#", line) for line in clean_entry.splitlines()):
        raise ValueError(
            "coordination entries cannot contain Markdown headings"
        )
    marker = _marker(conn)
    row = _row(conn.execute(
        "SELECT content, updated_at FROM strategy_docs "
        f"WHERE project_id = {marker} AND slug = {marker} FOR UPDATE",
        (int(project_id), slug),
    ))
    if row is None:
        raise StrategyDocMissingError(
            f"project {project_id} has no strategy doc {slug!r}"
        )
    content = _append_to_markdown_section(
        str(row["content"]), clean_section, clean_entry,
    )
    updated_at = next_updated_at()
    conn.execute(
        f"UPDATE {STRATEGY_DOCS_TABLE} "
        f"SET content = {marker}, updated_at = {marker}, "
        f"updated_by_actor_id = {marker} "
        f"WHERE project_id = {marker} AND slug = {marker}",
        (content, updated_at, actor_id, int(project_id), slug),
    )
    revision = record_doc_revision(
        conn,
        int(project_id),
        slug,
        content,
        source_operation=f"coordination_append:{clean_section.casefold().replace(' ', '_')}",
        actor_id=actor_id,
        session_id=session_id,
        created_at=updated_at,
    )
    conn.commit()
    return {
        "slug": slug,
        "section": clean_section,
        "revision": revision,
        "updated_at": updated_at,
        "bytes": len(content.encode("utf-8")),
    }


def blitz_completion_evidence(conn: Any, item_id: int) -> dict[str, Any]:
    """Derive the document-owned evidence needed to close a Blitz."""
    marker = _marker(conn)
    row = _row(conn.execute(
        "SELECT d.slug, d.content FROM item_strategy_docs l "
        "JOIN strategy_docs d ON d.project_id = l.project_id "
        "AND d.slug = l.strategy_doc_slug "
        f"WHERE l.item_id = {marker}",
        (int(item_id),),
    ))
    if row is None:
        return {
            "item_id": int(item_id),
            "satisfied": False,
            "missing": ["execution_document"],
        }
    content = str(row["content"])
    checks = {
        "completion": bool(re.search(r"\bcomplet(?:e|ed|ion)\b", content, re.I)),
        "remaining_work": bool(re.search(r"\bremain(?:s|ing)?\b", content, re.I)),
        "verification": bool(re.search(r"\b(?:verification|evidence|proof)\b", content, re.I)),
        "parent_reconciliation": bool(
            re.search(r"\bparent\b[\s\S]{0,80}\breconcil", content, re.I)
        ),
    }
    missing = [name for name, present in checks.items() if not present]
    return {
        "item_id": int(item_id),
        "slug": str(row["slug"]),
        "checks": checks,
        "missing": missing,
        "satisfied": not missing,
    }


__all__ = [
    "COORDINATION_SECTIONS",
    "append_strategy_coordination",
    "blitz_completion_evidence",
]
