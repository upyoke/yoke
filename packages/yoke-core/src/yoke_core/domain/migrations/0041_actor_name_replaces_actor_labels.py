"""Give every actor one name and retire the per-surface label projection.

``actor_labels`` stored a person's name once per surface — ``display``
for operator views, ``github_label`` for issue attribution — and the two
were the same string for every actor that had both. The surface split
bought nothing and cost something real: the ``github_label`` surface was
unique, so it doubled as a lookup key, and code that needed "who is
this?" answered it by matching a name. A rename then moved an identity,
and two people who shared a name could not both exist.

So the name moves onto ``actors.name``, with no uniqueness of any kind,
and nothing resolves an identity from it. Every durable reference —
sessions, claims, org and project roles, external identities, API
tokens — already keys on ``actors.id`` and is untouched here.

The backfill prefers the display name, then the GitHub label, then the
system component, because that is the order the readers being replaced
consulted; an actor carrying only one of them keeps exactly what it had.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _index_exists,
    _table_exists,
)


#: A build older than this entry renders every actor by reading
#: ``actor_labels``, so it cannot serve a database this entry has
#: converged: each session card, claim holder, and GitHub attribution
#: would fail on a table that is gone.
MINIMUM_SERVING_VERSION = NEXT_RELEASE

ACTORS_TABLE = "actors"
NAME_COLUMN = "name"
LABELS_TABLE = "actor_labels"

# Spelled out rather than imported from the live vocabulary. This entry is
# permanent history loaded from whatever tree runs it, and it must produce
# the same result whenever it runs; the modules that once defined these
# surfaces are removed by the same change that adds this entry.
DISPLAY_SURFACE = "display"
GITHUB_SURFACE = "github_label"
RESOLUTION_LABEL_INDEX = "uq_actor_labels_resolution_surface_label"
LABEL_ACTOR_INDEX = "idx_actor_labels_actor"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _backfill_names(conn: Any) -> None:
    """Copy each actor's best existing name onto ``actors.name``.

    Only rows whose name is still empty are written, so the entry is
    idempotent against its own output: a universe where the running code
    has already named an actor keeps that name rather than having a
    stale label copied back over it.
    """
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT a.id, "
        "(SELECT label FROM actor_labels al "
        f" WHERE al.actor_id = a.id AND al.surface = {marker}) AS display_name, "
        "(SELECT label FROM actor_labels al "
        f" WHERE al.actor_id = a.id AND al.surface = {marker}) AS github_name, "
        "a.system_component "
        "FROM actors a "
        "WHERE a.name IS NULL OR a.name = '' "
        "ORDER BY a.id",
        (DISPLAY_SURFACE, GITHUB_SURFACE),
    ).fetchall()
    for row in rows:
        actor_id = int(row[0])
        name = next(
            (str(value).strip() for value in row[1:4] if str(value or "").strip()),
            "",
        )
        if not name:
            continue
        conn.execute(
            f"UPDATE actors SET name = {marker} WHERE id = {marker}",
            (name, actor_id),
        )


def apply(conn: Any) -> None:
    """Add ``actors.name``, backfill it, and drop the label projection."""
    if not _table_exists(conn, ACTORS_TABLE):
        return

    _add_column_if_not_exists(
        conn, ACTORS_TABLE, NAME_COLUMN, "TEXT NOT NULL DEFAULT ''"
    )

    if _table_exists(conn, LABELS_TABLE):
        _backfill_names(conn)
        for index in (RESOLUTION_LABEL_INDEX, LABEL_ACTOR_INDEX):
            if _index_exists(conn, index, LABELS_TABLE):
                conn.execute(f'DROP INDEX IF EXISTS "{index}"')
        conn.execute(f'DROP TABLE "{LABELS_TABLE}"')


def invariants(conn: Any) -> None:
    """Assert the shape every reader of this build depends on."""
    if not _table_exists(conn, ACTORS_TABLE):
        return
    if not _column_exists(conn, ACTORS_TABLE, NAME_COLUMN):
        raise AssertionError("actors.name is missing after apply")
    if _table_exists(conn, LABELS_TABLE):
        raise AssertionError("actor_labels still exists after apply")


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
