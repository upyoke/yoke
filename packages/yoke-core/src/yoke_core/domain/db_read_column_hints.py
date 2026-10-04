"""Storage labels for diagnostic DB column suggestions."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionWarning


TEXT_STORED_SHAPES = {
    ("work_claims", "scope"): "JSON document stored as text",
    ("events", "envelope"): "JSON document stored as text",
    ("events", "created_at"): "timestamp stored as text",
}


def column_hint(table: str, name: str, storage_type: str) -> str:
    """Name both the SQL storage type and any structured text convention."""
    shape = TEXT_STORED_SHAPES.get((table, name))
    return f"{name} {storage_type}" + (f" ({shape})" if shape else "")


__all__ = ["column_hint", "TEXT_STORED_SHAPES"]


def item_reference_warnings(columns: list[str]) -> list[FunctionWarning]:
    """Warn when a diagnostic result loses the project's item identity."""
    names = {column.lower() for column in columns}
    if "project_sequence" not in names or names & {"public_item_prefix", "public_ref"}:
        return []
    return [
        FunctionWarning(
            code="project_sequence_unqualified",
            step="db.read.run",
            detail=(
                "project_sequence is unique only within a project. "
                "JOIN item_refs r ON r.item_id = items.id and SELECT r.public_ref, "
                "or include projects.public_item_prefix in the result."
            ),
        )
    ]
