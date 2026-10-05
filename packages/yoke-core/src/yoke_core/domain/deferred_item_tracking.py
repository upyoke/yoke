"""Deferred-work tracking on a task-graph parent's own text.

A task-graph parent records work it consciously left for later under a
``## Deferred Items`` heading, each entry filed as its own item. Two things
break that contract: an entry still marked unfiled, and deferral language
elsewhere in the item that names no filed item at all. The completion gate
refuses both before the parent reaches its successful terminal stage, and
the doctor reports the same findings on parents that already closed.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.schema_common import _get_columns, _table_exists

DEFERRED_ITEMS_HEADING = "## Deferred Items"

#: Narrative columns a parent's deferral language can live in.
DEFERRED_ITEM_FIELDS = (
    "spec",
    "design_spec",
    "technical_plan",
    "worktree_plan",
    "shepherd_caveats",
    "test_results",
    "deploy_log",
)

_DEFERRAL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"deferred to a follow-up",
        r"deferred to follow-up",
        r"isolated to a follow-up",
        r"isolated to follow-up",
        r"out of scope for this epic",
    )
)
_FILED_ITEM_REF = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")

UNFILED_ENTRY = "unfiled_entry"
UNTRACKED_DEFERRAL = "untracked_deferral"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def item_deferral_text(conn: Any, item_id: int) -> str:
    """Every narrative column and section of one item, as one document."""
    marker = _p(conn)
    fields = [
        field for field in DEFERRED_ITEM_FIELDS if field in _get_columns(conn, "items")
    ]
    chunks: list[str] = []
    if fields:
        row = query_one(
            conn,
            f"SELECT {', '.join(fields)} FROM items WHERE id = {marker}",
            (int(item_id),),
        )
        for field in fields:
            value = row[field] if row is not None else None
            if value is not None and str(value).strip() and str(value) != "null":
                chunks.append(str(value))
    if _table_exists(conn, "item_sections"):
        for section in query_rows(
            conn,
            "SELECT section_name, content FROM item_sections "
            f"WHERE item_id = {marker} ORDER BY ordering, section_name",
            (int(item_id),),
        ):
            content = section["content"]
            if content is not None and str(content).strip():
                chunks.append(f"## {section['section_name']}\n{content}")
    return "\n\n".join(chunks)


def deferral_findings(text: str) -> tuple[str, ...]:
    """Which of the two tracking breaks the text carries, in a stable order."""
    findings: list[str] = []
    in_section = False
    in_fence = False
    outside: list[str] = []
    unfiled = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if line.startswith(DEFERRED_ITEMS_HEADING):
            in_section = True
            continue
        if line.startswith("## "):
            in_section = False
        if in_section:
            unfiled = unfiled or "unfiled" in line.lower()
        elif not in_fence:
            outside.append(line)
    if unfiled:
        findings.append(UNFILED_ENTRY)
    if any(
        pattern.search(line) and not _FILED_ITEM_REF.search(line)
        for line in outside
        for pattern in _DEFERRAL_PATTERNS
    ):
        findings.append(UNTRACKED_DEFERRAL)
    return tuple(findings)


def describe_finding(finding: str) -> str:
    """One operator sentence per finding code."""
    if finding == UNFILED_ENTRY:
        return f"has UNFILED entries in its {DEFERRED_ITEMS_HEADING} section"
    return (
        "carries deferral language with no filed item reference and no "
        f"{DEFERRED_ITEMS_HEADING} tracking"
    )


__all__ = [
    "DEFERRED_ITEMS_HEADING",
    "DEFERRED_ITEM_FIELDS",
    "UNFILED_ENTRY",
    "UNTRACKED_DEFERRAL",
    "deferral_findings",
    "describe_finding",
    "item_deferral_text",
]
