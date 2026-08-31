"""Scope actor-label uniqueness to the surfaces that resolve a label.

``actor_labels`` was born with a global ``UNIQUE(surface, label)``, which
reads correctly for a resolution surface such as ``github_label``: the
label is a sync key, so it must name one actor. It reads wrongly for the
display surface, where the label is a person's name. Two members of one
organization can genuinely be called the same thing, and the constraint
would refuse the second one's name rather than prevent an ambiguity.

The retired constraint is replaced by a partial unique index covering
every surface except ``display``. Nothing is deleted or rewritten: this
relaxes what may be stored, so a build that predates it keeps reading and
writing ``actor_labels`` unchanged.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.actor_labels import DISPLAY_LABEL_SURFACE
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _connection_is_postgres,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    RESOLUTION_LABEL_INDEX,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "actor_labels"
RETIRED_CONSTRAINT = "actor_labels_surface_label_key"


def apply(conn: Any) -> None:
    """Retire the global label constraint and add the resolution-only index.

    Idempotent against its own output: a universe born after this entry
    already carries the partial index and never carried the constraint, so
    both statements are no-ops there.
    """
    if not _table_exists(conn, TABLE):
        return
    if _connection_is_postgres(conn):
        # The constraint owns its backing index, so DROP INDEX cannot
        # remove it; the constraint has to go first.
        conn.execute(
            f'ALTER TABLE "{TABLE}" DROP CONSTRAINT IF EXISTS "{RETIRED_CONSTRAINT}"'
        )
    conn.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS "{RESOLUTION_LABEL_INDEX}" '
        f'ON "{TABLE}"(surface, label) '
        f"WHERE surface <> '{DISPLAY_LABEL_SURFACE}'"
    )


def invariants(conn: Any) -> None:
    """Prove the display surface is free and resolution surfaces are not."""
    if not _table_exists(conn, TABLE):
        return
    assert _index_exists(conn, RESOLUTION_LABEL_INDEX, TABLE), (
        f"{RESOLUTION_LABEL_INDEX} must exist so a resolution-surface label "
        "still names at most one actor"
    )
    if _connection_is_postgres(conn):
        assert not _index_exists(conn, RETIRED_CONSTRAINT, TABLE), (
            f"{RETIRED_CONSTRAINT} must be absent so two actors may carry the "
            f"same {DISPLAY_LABEL_SURFACE!r} label"
        )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "RETIRED_CONSTRAINT",
    "TABLE",
    "apply",
    "invariants",
]
