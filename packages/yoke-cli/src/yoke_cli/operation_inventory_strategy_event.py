"""Operation-inventory rows for strategy/event/Ouroboros wrapper work."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import (
    REASON_TOOL_SHAPED,
    _p,
    _Row,
    _w,
)


WRAPPED_ROWS: Tuple[_Row, ...] = (
    _w("yoke events emit", "events"),
    _w("yoke ouroboros entry insert", "ouroboros"),
    _w("yoke ouroboros entry mark-reviewed", "ouroboros"),
    _w("yoke ouroboros entry mark-archived", "ouroboros"),
    _w("yoke ouroboros wrapup list", "ouroboros"),
    _w("yoke strategy carry register-new", "strategy.carry"),
    _w("yoke strategy carry candidate-set", "strategy.carry"),
    _w("yoke strategy carry summary", "strategy.carry"),
    _w("yoke strategy carry mark", "strategy.carry"),
    _w("yoke strategy checkpoint record", "strategy.checkpoint"),
    _w("yoke strategy checkpoint latest", "strategy.checkpoint"),
    _w("yoke strategy master-plan-check", "strategy"),
)


PERMANENT_ROWS: Tuple[_Row, ...] = (
    _p("python3 -m yoke_core.tools.atlas_render_docs render",
       "tools.atlas", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.atlas_render_docs check",
       "tools.atlas", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.session_init",
       "tools.session_init", REASON_TOOL_SHAPED),
)


__all__ = ["WRAPPED_ROWS", "PERMANENT_ROWS"]
