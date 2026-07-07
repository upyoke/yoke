"""Handler registrations for ``scratch.*`` function ids.

Currently registers ``scratch.dispatch_inputs`` — a thin read-only
resolver returning the helper-computed dispatch-inputs directory.
Domain-based naming (``_register_scratch`` rather than the legacy
ordinal ``_register_taskN`` pattern) sidesteps cross-epic collisions
on the same ordinal.
"""

from __future__ import annotations

from yoke_core.domain.handlers.scratch_dispatch_inputs import (
    REGISTRATIONS as _SCRATCH_DISPATCH_INPUTS_REGS,
)


def register(registry) -> None:
    """Register every ``scratch.*`` handler via the given registry module."""

    for entry in _SCRATCH_DISPATCH_INPUTS_REGS:
        if registry.lookup(entry["function_id"]) is None:
            registry.register(**entry)
