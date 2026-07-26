"""Operation inventory rows for workflow version operators."""

from yoke_cli.operation_inventory_model import _Row, _w

WRAPPED_ROWS: tuple[_Row, ...] = (
    _w("yoke workflows definition get", "workflows"),
    _w("yoke workflows version get", "workflows"),
    _w("yoke workflows item get", "workflows"),
    _w("yoke workflows current set", "workflows"),
    _w("yoke workflows policy-defaults publish", "workflows"),
    _w("yoke workflows item migrate", "workflows"),
)

__all__ = ["WRAPPED_ROWS"]
