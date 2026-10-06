"""Session chain budget configuration."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.machine_config.settings_keys import machine_setting_default
from yoke_core.api.routing_config import parse_config_file


def get_max_chain_steps(config_path: str | Path) -> int:
    """Read the session budget, falling back to its declared setting default."""
    default = int(machine_setting_default("max_chain_steps"))
    try:
        return int(parse_config_file(config_path).get("max_chain_steps", default))
    except (ValueError, TypeError):
        return default
