"""Handler registrations for ouroboros.field_note.* handlers.

The field-note channel persists agent-authored signals to the
authoritative ``ouroboros_entries`` table and emits one
``OuroborosFieldNoteAppended`` event per call for telemetry. The kind
vocabulary is ``failed | new | unclear | observation``; ``/yoke curate``
reads the durable rows.
"""
from __future__ import annotations

from yoke_core.domain.handlers import ouroboros_field_note


def register(registry) -> None:
    """Register field-note handlers via the given registry module."""
    for entry in ouroboros_field_note.REGISTRATIONS:
        registry.register(**entry)
