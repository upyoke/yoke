"""Organization identity and settings CLI registry entries."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters import organizations as _adapters


AdapterFn = Callable[[List[str]], int]

ORGANIZATION_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("organizations", "get"): (
        "organizations.get",
        _adapters.organizations_get,
    ),
    ("organizations", "settings", "get"): (
        "organizations.settings.get",
        _adapters.organizations_settings_get,
    ),
    ("organizations", "settings", "merge"): (
        "organizations.settings.merge",
        _adapters.organizations_settings_merge,
    ),
    ("organizations", "domain", "set"): (
        "organizations.domain.set",
        _adapters.organizations_domain_set,
    ),
}

__all__ = ["ORGANIZATION_SUBCOMMAND_REGISTRY"]
