"""Permanent operation rows for installer-local command families."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import (
    REASON_TOOL_SHAPED,
    _p,
    _Row,
)


# These commands operate on the caller's machine and deliberately have no
# dispatcher function id. The tool-shaped registry routes them after the
# registered-function lookup misses.
PERMANENT_ROWS: Tuple[_Row, ...] = (
    _p("yoke aws exec", "aws", REASON_TOOL_SHAPED),
    _p("yoke github connect", "github", REASON_TOOL_SHAPED),
    _p("yoke github disconnect", "github", REASON_TOOL_SHAPED),
    _p("yoke github status", "github", REASON_TOOL_SHAPED),
    _p("yoke dev setup", "dev", REASON_TOOL_SHAPED),
    _p("yoke dev db-admin setup", "dev", REASON_TOOL_SHAPED),
    _p("yoke dev path-snapshot-prewarm", "dev", REASON_TOOL_SHAPED),
    _p("yoke onboard", "onboard", REASON_TOOL_SHAPED),
    _p("yoke onboard project", "onboard", REASON_TOOL_SHAPED),
    _p("yoke project create", "project", REASON_TOOL_SHAPED),
    _p("yoke project import", "project", REASON_TOOL_SHAPED),
    _p("yoke runner-fleet exec", "runner_fleet", REASON_TOOL_SHAPED),
    _p("yoke pulumi exec", "pulumi", REASON_TOOL_SHAPED),
)


__all__ = ["PERMANENT_ROWS"]
