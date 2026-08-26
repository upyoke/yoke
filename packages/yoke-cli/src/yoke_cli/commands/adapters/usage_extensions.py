"""Compose usage catalogs that live in focused adapter modules."""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands.adapters import claims_coordination_lease
from yoke_cli.commands.adapters import claims_steering
from yoke_cli.commands.adapters import qa
from yoke_cli.commands.adapters import shepherd_writes
from yoke_cli.commands.adapters import strategy_event_usage
from yoke_cli.commands.adapters import usage_composed_operations
from yoke_cli.commands.adapters import usage_product_surfaces
from yoke_cli.commands.adapters.usage_readiness import READINESS_USAGE_BY_ID


def extend_adapter_usage(target: Dict[str, str]) -> None:
    """Add the usage maps maintained outside the core catalog."""
    target.update(READINESS_USAGE_BY_ID)
    target.update(qa.USAGE_BY_FUNCTION_ID)
    target.update(shepherd_writes.USAGE_BY_FUNCTION_ID)
    target.update(strategy_event_usage.USAGE_BY_FUNCTION_ID)
    target.update(usage_composed_operations.USAGE_BY_FUNCTION_ID)
    target.update(usage_product_surfaces.USAGE_BY_FUNCTION_ID)
    target.update(claims_coordination_lease.USAGE_BY_FUNCTION_ID)
    target.update(claims_steering.USAGE_BY_FUNCTION_ID)


__all__ = ["extend_adapter_usage"]
