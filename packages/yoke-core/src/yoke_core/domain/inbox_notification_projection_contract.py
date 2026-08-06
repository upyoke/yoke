"""Stable storage contract for inbox notification delivery snapshots."""

from __future__ import annotations

from typing import Final


DELIVERY_SNAPSHOT_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("event_name", "TEXT"),
    ("project_id", "INTEGER"),
    ("event_outcome", "TEXT"),
    ("event_actor_id", "INTEGER"),
    ("event_actor_label", "TEXT"),
    ("event_envelope", "TEXT"),
)


__all__ = ["DELIVERY_SNAPSHOT_COLUMNS"]
