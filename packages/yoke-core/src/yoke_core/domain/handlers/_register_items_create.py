"""Handler registration for ``items.create`` (sanctioned idea-intake create).

Kept as its own registrar (not folded into ``_register_items_scalar_lifecycle``)
because create is a distinct, no-claim, global-target concern from the
item-claim-gated scalar/lifecycle writes; per-concern registrar files keep the
shared edit point keyed to the handler concern.
"""
from __future__ import annotations

from yoke_core.domain.handlers.items_create import (
    REGISTRATIONS as _ITEMS_CREATE_REGS,
)


def register(registry) -> None:
    """Register items.create via the given registry module."""
    for _entry in _ITEMS_CREATE_REGS:
        if registry.lookup(_entry["function_id"]) is None:
            registry.register(**_entry)
