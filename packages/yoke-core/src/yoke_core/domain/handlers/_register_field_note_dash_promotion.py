"""Leaf registration hook for field-note promotion."""

from yoke_core.domain.handlers.field_note_dash_promotion import REGISTRATIONS


def register(registry) -> None:
    for entry in REGISTRATIONS:
        registry.register(**entry)


__all__ = ["register"]
