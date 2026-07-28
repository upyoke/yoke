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
    _w("yoke items get", "items.read"),
    _w("yoke item-worktrees get", "item_worktrees"),
    _w("yoke item-worktrees release", "item_worktrees"),
    _w("yoke test-machine get", "test_machine"),
    _w("yoke test-machine settings-replace", "test_machine"),
    _w("yoke test-machine verify", "test_machine"),
)
PERMANENT_ROWS = DIRECT_WORKFLOW_PERMANENT_ROWS


__all__ = ["PERMANENT_ROWS", "WRAPPED_ROWS"]
