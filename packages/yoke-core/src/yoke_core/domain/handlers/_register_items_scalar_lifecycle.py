"""Handler registrations for items.scalar.update +
lifecycle.transition + lifecycle.skip handlers.
"""
from __future__ import annotations

from yoke_core.domain.handlers.items_scalar import (
    REGISTRATIONS as _ITEMS_SCALAR_REGS,
)
from yoke_core.domain.handlers.lifecycle_skip import (
    REGISTRATIONS as _LIFECYCLE_SKIP_REGS,
)
from yoke_core.domain.handlers.lifecycle_transition import (
    REGISTRATIONS as _LIFECYCLE_TRANSITION_REGS,
)


def register(registry) -> None:
    """Register task 5's handlers via the given registry module."""
    for _entry in (
        _ITEMS_SCALAR_REGS
        + _LIFECYCLE_TRANSITION_REGS
        + _LIFECYCLE_SKIP_REGS
    ):
        if registry.lookup(_entry["function_id"]) is None:
            registry.register(**_entry)
