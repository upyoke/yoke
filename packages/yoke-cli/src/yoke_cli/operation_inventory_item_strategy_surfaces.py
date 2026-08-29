"""Operation rows for workflow-aware item and strategy execution reads."""

from yoke_cli.operation_inventory_model import _Row, _w


WRAPPED_ROWS: tuple[_Row, ...] = (
    _w("yoke items overview list", "items.read"),
    _w("yoke items detail get", "items.read"),
    _w("yoke items public-ref lookup", "items.read"),
    _w("yoke strategy surface list", "strategy"),
    _w("yoke strategy surface get", "strategy"),
    _w("yoke strategy revision diff", "strategy"),
    _w("yoke strategy revision restore", "strategy"),
    _w("yoke strategy parent set", "strategy"),
    _w("yoke strategy coordination append", "strategy"),
    _w("yoke strategy execution get", "strategy.execution"),
    _w("yoke strategy execution link", "strategy.execution"),
    _w("yoke strategy claim acquire", "strategy.claim"),
    _w("yoke strategy claim release", "strategy.claim"),
    _w("yoke strategy claim break-glass-release", "strategy.claim"),
    _w("yoke strategy doc-claim acquire", "strategy.doc_claim"),
    _w("yoke strategy doc-claim release", "strategy.doc_claim"),
    _w("yoke strategy doc-claim list", "strategy.doc_claim"),
)


__all__ = ["WRAPPED_ROWS"]
