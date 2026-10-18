"""Column and item-reference teaching for diagnostic DB reads and packets."""

from __future__ import annotations

import re

from yoke_contracts.api.function_call import FunctionWarning


TEXT_STORED_SHAPES = {
    ("work_claims", "scope"): "JSON document stored as text",
    ("events", "envelope"): "JSON document stored as text",
    ("events", "created_at"): "timestamp stored as text",
}

ITEM_REFS_LINE = (
    "Show item ids as public refs (PREFIX-N): JOIN item_refs r ON r.item_id = "
    "<item id column> (items.id or any *item_id) and SELECT r.public_ref."
)

_ITEM_ID_COLUMN_RE = re.compile(r"\b\w*item_id\b", re.IGNORECASE)
_ITEMS_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+(?:\w+\.)?\"?items\"?(?:\s+(?:AS\s+)?(\w+))?",
    re.IGNORECASE,
)
_ITEM_REFS_RE = re.compile(r"\bitem_refs\b", re.IGNORECASE)
_SQL_KEYWORDS = {
    "where",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "full",
    "cross",
    "on",
    "group",
    "order",
    "limit",
    "union",
    "having",
}


def column_hint(table: str, name: str, storage_type: str) -> str:
    """Name both the SQL storage type and any structured text convention."""
    shape = TEXT_STORED_SHAPES.get((table, name))
    return f"{name} {storage_type}" + (f" ({shape})" if shape else "")


def is_item_id_column(table: str, name: str) -> bool:
    """True for ``items.id`` and every ``*item_id`` column."""
    lowered = name.lower()
    return lowered.endswith("item_id") or (table == "items" and lowered == "id")


def sql_touches_item_ids(sql: str) -> bool:
    """True when SQL reads an item id without already joining ``item_refs``."""
    if _ITEM_REFS_RE.search(sql):
        return False
    if _ITEM_ID_COLUMN_RE.search(sql):
        return True
    for match in _ITEMS_TABLE_RE.finditer(sql):
        alias = (match.group(1) or "").lower()
        names = ["items"] + ([alias] if alias and alias not in _SQL_KEYWORDS else [])
        qualified = "|".join(re.escape(name) for name in names)
        if re.search(
            rf"\b(?:{qualified})\.(?:id\b|\*)|(?<!\.)\bid\b|SELECT\s+\*",
            sql,
            re.IGNORECASE,
        ):
            return True
    return False


def table_notes(table: str, columns: list[tuple[str, str]], notes: str) -> str:
    """Lead a table's packet notes with item_refs when it carries item ids."""
    if table == "item_refs" or not any(
        is_item_id_column(table, name) for name, _ in columns
    ):
        return notes
    return f"{ITEM_REFS_LINE} {notes}".strip()


def item_reference_warnings(sql: str, columns: list[str]) -> list[FunctionWarning]:
    """Warn when a diagnostic read shows item ids without public refs."""
    warnings: list[FunctionWarning] = []
    if sql_touches_item_ids(sql):
        warnings.append(
            FunctionWarning(
                code="item_refs_not_joined",
                step="db.read.run",
                detail=ITEM_REFS_LINE,
            )
        )
    names = {column.lower() for column in columns}
    if "project_sequence" in names and not names & {"public_item_prefix", "public_ref"}:
        warnings.append(
            FunctionWarning(
                code="project_sequence_unqualified",
                step="db.read.run",
                detail=(
                    "project_sequence is unique only within a project. "
                    "JOIN item_refs r ON r.item_id = items.id and SELECT r.public_ref, "
                    "or include projects.public_item_prefix in the result."
                ),
            )
        )
    return warnings


__all__ = [
    "ITEM_REFS_LINE",
    "TEXT_STORED_SHAPES",
    "column_hint",
    "is_item_id_column",
    "item_reference_warnings",
    "sql_touches_item_ids",
    "table_notes",
]
