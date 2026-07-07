"""Actor resolution, seeding, and central label rendering.

Owns the read/write path for the ``actors`` and ``actor_labels`` tables
created in :mod:`schema_init_actor_path_claim_tables`. Three concerns
live here:

1. **Seeding.** Idempotent helpers create the canonical system actor
   (``yoke-core``) and per-call human actors. Seeding is migration-
   safe: every helper uses ``INSERT ... ON CONFLICT DO NOTHING`` against
   the column or partial index that defines uniqueness, then returns the
   row id.
2. **Resolution.** ``resolve_actor_by_label`` returns the actor id for a
   given external label on a given surface, or ``None`` if no mapping
   exists. New write paths use this to convert legacy text source labels
   into actor FK values; live consumers use it for inbound GitHub label
   reconciliation.
3. **Central label rendering.** :func:`actor_label` is the single
   sanctioned helper that turns an ``actors.id`` into an external label
   token for a named surface. It is fail-closed: callers must never
   invent fallback strings on missing or ambiguous data, because the
   raw numeric actor id leaking into a GitHub label or operator-facing
   surface is the failure mode the central helper exists to prevent.

Why fail-closed instead of return-None? The render call sites are label
emitters — every code path that holds an actor id and asks for "the
label" is about to write that string somewhere external. Returning
``None`` (or the raw id) silently produces a malformed label such as
``source:7`` against GitHub. Raising :class:`ActorLabelMissing` forces
the caller to either seed the missing label or surface a well-typed
error.

This module deliberately does **not** introduce a profile abstraction or
a User-record adapter. ``actor_labels`` is a surface-specific projection;
future User identity attaches to ``actors.id`` in a later generation, and
this module's helpers are the upstream the later layer extends.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend

DISPLAY_LABEL_SURFACE = "display"
GITHUB_LABEL_SURFACE = "github_label"
SYSTEM_COMPONENT_YOKE_CORE = "yoke-core"

#: Env var that injects the local human actor's label into canonical-actor
#: seeding. The environment-bootstrap init chain invokes each init module
#: as ``main(["init"])`` with no parameters, so per-universe context rides
#: pinned env vars (the same idiom as the ``YOKE_PG_DSN`` authority pin);
#: the local-universe birth path pins this to the OS login so a fresh
#: machine-local universe labels its human actor with its actual owner.
LOCAL_HUMAN_LABEL_ENV = "YOKE_LOCAL_HUMAN_LABEL"

#: Fallback label when no explicit label or env injection is present.
#: Matches the label the one-shot migration mapped onto the existing
#: authoritative DB's human actor, so re-init against that DB resolves the
#: existing row instead of creating a duplicate human.
DEFAULT_LOCAL_HUMAN_LABEL = "ben"


class ActorError(Exception):
    """Base class for actor-resolution failures."""


class ActorLabelMissing(ActorError):
    """A label-render request found no mapping for the given actor and surface."""


class ActorLabelAmbiguous(ActorError):
    """A label-render request found multiple labels for the same actor/surface.

    Should be unreachable given the ``UNIQUE(actor_id, surface)`` index
    on :data:`actor_labels`, but raised explicitly so a future schema
    weakening cannot silently produce arbitrary label output.
    """


class ActorNotFound(ActorError):
    """An actor id was looked up that does not exist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def seed_system_actor(
    conn: Any,
    system_component: str,
) -> int:
    """Idempotently insert a system actor with the given component name.

    Returns the actor id. The partial UNIQUE index on
    ``actors.system_component`` (``WHERE system_component IS NOT NULL``)
    cannot be referenced by ``ON CONFLICT`` because SQLite does not
    consider partial indexes as conflict targets, so the helper
    SELECTs first and only INSERTs on a miss.
    """
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT id FROM actors WHERE system_component = {p}",
        (system_component,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cur = conn.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        f"VALUES ('system', {p}, {p}) RETURNING id",
        (system_component, _now()),
    )
    actor_id = int(cur.fetchone()[0])
    conn.commit()
    return actor_id


def seed_human_actor(conn: Any) -> int:
    """Insert a new human actor row and return its id.

    Human actors are not de-duplicated by any column; the
    caller decides identity. The migration uses one human row per legacy
    text source value found in ``items.source``.
    """
    p = _placeholder(conn)
    cur = conn.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        f"VALUES ('human', NULL, {p}) RETURNING id",
        (_now(),),
    )
    actor_id = int(cur.fetchone()[0])
    conn.commit()
    return actor_id


def set_actor_label(
    conn: Any,
    actor_id: int,
    label: str,
    *,
    surface: str = GITHUB_LABEL_SURFACE,
) -> None:
    """Idempotently bind an actor to a label on the given surface.

    Re-running with the same ``(actor_id, surface)`` pair is a silent
    no-op — the prior label remains. Callers that need to relabel must
    delete the existing row deliberately. The
    ``UNIQUE(actor_id, surface)`` constraint guarantees the central
    rendering helper sees at most one label per surface per actor.
    """
    p = _placeholder(conn)
    existing = conn.execute(
        f"SELECT 1 FROM actor_labels WHERE actor_id = {p} AND surface = {p}",
        (actor_id, surface),
    ).fetchone()
    if existing is not None:
        return
    conn.execute(
        "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (actor_id, surface, label, _now()),
    )
    conn.commit()


def resolve_actor_by_label(
    conn: Any,
    label: str,
    *,
    surface: str = GITHUB_LABEL_SURFACE,
) -> Optional[int]:
    """Return the actor id bound to ``label`` on ``surface``, or None.

    Used by inbound GitHub label reconciliation, by the migration's
    legacy-source-label conversion path, and by the actor-resolution
    fallback in :mod:`backlog_create_op`.
    """
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT actor_id FROM actor_labels "
        f"WHERE surface = {p} AND label = {p}",
        (surface, label),
    ).fetchone()
    return int(row[0]) if row is not None else None


def actor_label(
    conn: Any,
    actor_id: int,
    *,
    surface: str = GITHUB_LABEL_SURFACE,
) -> str:
    """Render an actor id to its external label token on ``surface``.

    Fail-closed central helper. Callers MUST go through this function
    rather than reading ``actor_labels`` ad hoc — the central path is
    the only place in production code that converts a numeric actor id
    into a label string.

    System actors render their ``system_component`` token directly for
    the GitHub label surface. Human actors render through the
    ``actor_labels`` projection.

    Raises:
        ActorLabelMissing: no label is registered for the given actor
            and surface.
        ActorLabelAmbiguous: multiple labels are registered (schema
            weakened — should be unreachable).
        ActorNotFound: the actor id does not exist.
    """
    p = _placeholder(conn)
    actor_row = conn.execute(
        f"SELECT kind, system_component FROM actors WHERE id = {p}",
        (actor_id,),
    ).fetchone()
    if actor_row is None:
        raise ActorNotFound(f"actor id {actor_id} does not exist")
    kind, system_component = actor_row

    if surface == GITHUB_LABEL_SURFACE and kind == "system":
        if system_component is None:
            raise ActorLabelMissing(
                f"system actor {actor_id} has no system_component"
            )
        return str(system_component)

    rows = conn.execute(
        f"SELECT label FROM actor_labels WHERE actor_id = {p} AND surface = {p}",
        (actor_id, surface),
    ).fetchall()
    if not rows:
        raise ActorLabelMissing(
            f"actor {actor_id} has no label on surface {surface!r}"
        )
    if len(rows) > 1:
        raise ActorLabelAmbiguous(
            f"actor {actor_id} has {len(rows)} labels on surface {surface!r}"
        )
    return str(rows[0][0])


def seed_canonical_actors(
    conn: Any,
    *,
    local_human_label: Optional[str] = None,
) -> tuple[int, int]:
    """Seed the two actors every Yoke install needs and return their ids.

    Returns ``(yoke_core_id, local_human_id)``. Idempotent: re-running
    on a DB that already carries both actors short-circuits via the
    seeding helpers' own conflict handling.

    The human label resolves explicit argument first, then the
    :data:`LOCAL_HUMAN_LABEL_ENV` injection (how the no-argument init
    chain passes the universe owner's OS login through), then
    :data:`DEFAULT_LOCAL_HUMAN_LABEL`.

    The local human actor is looked up by label rather than created
    blindly, so a DB that already mapped a different label to the
    local human (for example via the one-shot migration) is honoured
    rather than duplicated.
    """
    label = (
        local_human_label
        or os.environ.get(LOCAL_HUMAN_LABEL_ENV, "").strip()
        or DEFAULT_LOCAL_HUMAN_LABEL
    )
    yoke_core = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    set_actor_label(conn, yoke_core, SYSTEM_COMPONENT_YOKE_CORE)

    existing = resolve_actor_by_label(conn, label)
    if existing is not None:
        return yoke_core, existing
    local_human = seed_human_actor(conn)
    set_actor_label(conn, local_human, label)
    return yoke_core, local_human


def actor_label_or_passthrough(
    conn: Any,
    value: str,
    *,
    surface: str = GITHUB_LABEL_SURFACE,
) -> str:
    """Render a column-stored actor token to a label, with a legacy passthrough.

    Reader adapter for the cutover window between writer-side migration
    (``execute_create`` stores stringified ``actors.id``
    values in ``items.source`` / ``items.owner``) and the live-apply
    backfill. During that window the same column may hold
    either:

    * a numeric actor id (rows written by the new path), or
    * a legacy text label such as ``ben`` / ``user`` /
      ``skill-simulate`` (rows untouched since the migration declared
      its mapping).

    Numeric values resolve through :func:`actor_label` and inherit its
    fail-closed contract — an orphan id with no actor row, or no label
    on the requested surface, raises :class:`ActorError` rather than
    leaking a malformed external token. Non-numeric values are returned
    unchanged so the GitHub render keeps producing operator-readable
    labels for pre-migration data.

    Empty / null sentinels (``""``, ``"null"``, ``"None"``) collapse to
    the empty string so callers can rely on the "render label only when
    truthy" pattern they already use for other categories.
    """
    if not value or value in ("null", "None"):
        return ""
    try:
        actor_id = int(value)
    except ValueError:
        return value
    return actor_label(conn, actor_id, surface=surface)


def labels_for_surface(
    conn: Any,
    surface: str = GITHUB_LABEL_SURFACE,
) -> Iterable[tuple[int, str]]:
    """Yield ``(actor_id, label)`` pairs registered for the given surface.

    Used by GitHub label sync to enumerate the canonical token set for
    category-keyed reconciliation, and by the resync comparator to
    rebuild expected ``source:*`` / ``owner:*`` label sets.
    """
    p = _placeholder(conn)
    return [
        (int(row[0]), str(row[1]))
        for row in conn.execute(
            f"SELECT actor_id, label FROM actor_labels WHERE surface = {p}",
            (surface,),
        )
    ]


def validate_actor_id(conn: Any, actor_id: int) -> bool:
    """Return True iff ``actor_id`` references an existing row."""
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {p}",
        (actor_id,),
    ).fetchone()
    return row is not None


__all__ = [
    "ActorError",
    "ActorLabelAmbiguous",
    "ActorLabelMissing",
    "ActorNotFound",
    "DEFAULT_LOCAL_HUMAN_LABEL",
    "DISPLAY_LABEL_SURFACE",
    "GITHUB_LABEL_SURFACE",
    "LOCAL_HUMAN_LABEL_ENV",
    "SYSTEM_COMPONENT_YOKE_CORE",
    "actor_label",
    "actor_label_or_passthrough",
    "labels_for_surface",
    "resolve_actor_by_label",
    "seed_canonical_actors",
    "seed_human_actor",
    "seed_system_actor",
    "set_actor_label",
    "validate_actor_id",
]
