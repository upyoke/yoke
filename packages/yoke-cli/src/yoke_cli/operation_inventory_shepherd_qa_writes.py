"""Recovery rows for shepherd verdict and QA waiver writers."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import _Row, _w


WRAPPED_ROWS: Tuple[_Row, ...] = (
    _w("yoke qa requirement waive", "qa.requirement"),
    _w("yoke items dependency add", "items.dependency"),
    _w("yoke items dependency update", "items.dependency"),
    _w("yoke items dependency remove", "items.dependency"),
    _w("yoke shepherd verdict", "shepherd"),
    _w("yoke shepherd caveat-disposition", "shepherd"),
)


__all__ = ["WRAPPED_ROWS"]
