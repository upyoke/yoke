"""Handler registrations for items.structured_field.* +
items.section.* + items.progress_log.* handlers.

The four structured-field registrations are composed in the sibling
``items_structured_field_models`` module to avoid the typed-models <->
handler-callables import cycle; the section and progress-log modules
expose their own ``REGISTRATIONS`` list.
"""
from __future__ import annotations

from yoke_core.domain.handlers import items_progress_log, items_section
from yoke_core.domain.handlers.items_structured_field_models import (
    build_registrations as _structured_field_registrations,
)


def register(registry) -> None:
    """Register task 3's handlers via the given registry module."""
    for entry in _structured_field_registrations():
        registry.register(**entry)
    for entry in items_section.REGISTRATIONS:
        registry.register(**entry)
    for entry in items_progress_log.REGISTRATIONS:
        registry.register(**entry)
