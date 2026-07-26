"""Operation inventory rows for Dash and Blitz direct execution."""

from yoke_cli.operation_inventory_model import REASON_TOOL_SHAPED, _p, _Row, _w

WRAPPED_ROWS: tuple[_Row, ...] = (
    _w("yoke dash", "items.create"),
    _w("yoke direct-workflow dash survey", "direct_workflow.dash"),
    _w("yoke direct-workflow blitz survey", "direct_workflow.blitz"),
    _w("yoke direct-workflow dash evidence", "direct_workflow.dash"),
    _w("yoke direct-workflow dash escalate", "direct_workflow.dash"),
    _w("yoke ouroboros field-note promote", "ouroboros"),
)

PERMANENT_ROWS: tuple[_Row, ...] = (
    _p(
        "yoke direct-workflow worktree prepare",
        "direct_workflow.worktree",
        REASON_TOOL_SHAPED,
    ),
)

__all__ = ["PERMANENT_ROWS", "WRAPPED_ROWS"]
