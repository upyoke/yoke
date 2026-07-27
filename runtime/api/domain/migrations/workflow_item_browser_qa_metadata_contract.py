"""Compatibility import for the governed Browser QA metadata contraction."""

from yoke_core.domain.migrations.workflow_item_browser_qa_metadata_contract import (
    MIGRATION_NAME,
    apply,
    invariants,
)

__all__ = ["MIGRATION_NAME", "apply", "invariants"]
