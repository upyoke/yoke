"""Operation inventory rows for workflow-aware product surfaces."""

from yoke_cli.operation_inventory_direct_workflows import (
    PERMANENT_ROWS as DIRECT_WORKFLOW_PERMANENT_ROWS,
    WRAPPED_ROWS as DIRECT_WORKFLOW_WRAPPED_ROWS,
)
from yoke_cli.operation_inventory_item_strategy_surfaces import (
    WRAPPED_ROWS as ITEM_STRATEGY_SURFACE_WRAPPED_ROWS,
)
from yoke_cli.operation_inventory_model import _w
from yoke_cli.operation_inventory_qa_catalog import (
    WRAPPED_ROWS as QA_CATALOG_WRAPPED_ROWS,
)


WRAPPED_ROWS = (
    *DIRECT_WORKFLOW_WRAPPED_ROWS,
    *ITEM_STRATEGY_SURFACE_WRAPPED_ROWS,
    *QA_CATALOG_WRAPPED_ROWS,
    _w("yoke inbox list", "inbox"),
    _w("yoke decision-requests dispose-ended", "decision_requests"),
    _w("yoke decision-requests resolve", "decision_requests"),
    _w("yoke items get", "items.read"),
    _w("yoke item-worktrees create", "item_worktrees"),
    _w("yoke item-worktrees get", "item_worktrees"),
    _w("yoke item-worktrees list", "item_worktrees"),
    _w("yoke item-worktrees path-record", "item_worktrees"),
    _w("yoke item-worktrees release", "item_worktrees"),
    _w("yoke test-machine get", "test_machine"),
    _w("yoke test-machine list", "test_machine"),
    _w("yoke test-machine settings-replace", "test_machine"),
    _w("yoke test-machine verify", "test_machine"),
    _w("yoke overview activation get", "overview"),
    _w("yoke harness machine-report upsert", "harness.machine_report"),
)
PERMANENT_ROWS = DIRECT_WORKFLOW_PERMANENT_ROWS


__all__ = ["PERMANENT_ROWS", "WRAPPED_ROWS"]
