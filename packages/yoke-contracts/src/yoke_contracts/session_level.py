"""Recognize retired settings keys for write refusals and convergence."""

from __future__ import annotations

from typing import Any, Mapping


EXECUTOR_DEFAULT_LEVEL_PREFIX = "executor_default_level_"


def retired_lane_setting_keys(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Identify removed action-permission keys for refusal and data convergence."""
    return tuple(
        key for key in settings if key == "lane_paths" or key.startswith("lane_paths_")
    )


def retired_process_offer_keys(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Identify removed process policy for write refusals and convergence."""
    return tuple(
        key
        for key in settings
        if key in {"process_offer", "process_offers"}
        or key.startswith("do_process_offer_")
    )


#: Session-routing keys retired when levels became ordered option lists held
#: as universe defaults: declared metadata, selector rules, and harness
#: defaults. Labeling now derives from each level's options.
RETIRED_LEVEL_ROUTING_KEYS: tuple[str, ...] = (
    "level_metadata",
    "level_rules",
    "executor_default_levels",
)


def retired_level_routing_keys(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Identify retired level routing keys for refusal and data convergence."""
    return tuple(
        key
        for key in settings
        if key in RETIRED_LEVEL_ROUTING_KEYS
        or (isinstance(key, str) and key.startswith(EXECUTOR_DEFAULT_LEVEL_PREFIX))
    )


__all__ = [
    "EXECUTOR_DEFAULT_LEVEL_PREFIX",
    "RETIRED_LEVEL_ROUTING_KEYS",
    "retired_level_routing_keys",
    "retired_lane_setting_keys",
    "retired_process_offer_keys",
]
