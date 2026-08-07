"""Operation inventory rows for workflow version operators."""

from yoke_cli.operation_inventory_model import _Row, _w

WRAPPED_ROWS: tuple[_Row, ...] = (
    _w("yoke workflows definition get", "workflows"),
    _w("yoke workflows version get", "workflows"),
    _w("yoke workflows version list", "workflows"),
    _w("yoke workflows item get", "workflows"),
    _w("yoke workflows current set", "workflows"),
    _w("yoke workflows policy-defaults publish", "workflows"),
    _w("yoke workflows item migrate", "workflows"),
    _w("yoke workflows mechanics get", "workflows"),
    _w("yoke workflows testing-default set", "workflows"),
    _w("yoke workflows delivery-default set", "workflows"),
    _w("yoke workflows approval-defaults publish", "workflows"),
    _w("yoke workflow execution-instruction create", "workflow.execution_instruction"),
    _w("yoke workflow execution-instruction update", "workflow.execution_instruction"),
    _w("yoke workflow execution-instruction set-scope", "workflow.execution_instruction"),
    _w("yoke workflow execution-instruction list", "workflow.execution_instruction"),
    _w("yoke workflow execution-instruction delete", "workflow.execution_instruction"),
)

__all__ = ["WRAPPED_ROWS"]
