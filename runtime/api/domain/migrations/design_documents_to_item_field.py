"""Source-checkout wrapper for design-document storage consolidation."""

from yoke_core.domain.migrations.design_documents_to_item_field import (
    ITEMS_TABLE,
    SOURCE_TABLE,
    TARGET_COLUMN,
    apply,
    invariants,
)

__all__ = [
    "ITEMS_TABLE",
    "SOURCE_TABLE",
    "TARGET_COLUMN",
    "apply",
    "invariants",
]
