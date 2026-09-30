"""Storage labels for diagnostic DB column suggestions."""

from __future__ import annotations


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
