"""Column shape a permanent history entry still names.

The surface these columns belonged to is gone, and no live code path reads
them. The ordered migration history is permanent, though, and the entry that
once added and backfilled them loads this module by name — a database born
before that entry still has to be able to apply it. Nothing new should import
this.
"""

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
