"""Handler registrations for ``items.github_sync``."""

from __future__ import annotations

from yoke_core.domain.handlers import items_github_sync


def register(registry) -> None:
    """Register item GitHub sync handlers via the given registry."""
    for entry in items_github_sync.REGISTRATIONS:
        registry.register(**entry)
