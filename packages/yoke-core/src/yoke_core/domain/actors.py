"""Actor seeding, naming, and name search.

Owns the read/write path for the ``actors`` table created in
:mod:`schema_init_actor_path_claim_tables`. Three concerns live here:

1. **Seeding.** Idempotent helpers create the canonical system actor
   (``yoke-core``) and human actors. Seeding is migration-safe: every
   helper resolves the row that already exists before inserting, then
   returns its id.
2. **Naming.** :func:`actor_name` renders an ``actors.id`` to its stored
   human-readable name, :func:`actor_display_labels` disambiguates shared
   names inside one display set, and :func:`set_actor_name` writes the name.
   There is exactly one stored name per actor: a name is what we call someone,
   and the same thing is true of them in the board, the CLI, a GitHub
   attribution label, and a session message.
3. **Name search.** :func:`resolve_actors_by_name` answers "who is
   called this?" for an operator who typed a name, and answers it as a
   list. It is deliberately not a resolution primitive: nothing that
   selects a session identity, an authenticated caller, or an owner may
   use it, because a name is neither unique nor stable. Identity is
   ``actors.id``, and every durable reference — sessions, claims, org
   and project roles, external identities, API tokens — stores that id.
   Renaming an actor therefore changes what people read and nothing
   else, and two people who share a name stay two people.

Reading is fail-closed: :func:`actor_name` raises rather than inventing
a fallback string, because every caller holding an actor id and asking
for a name is about to write it somewhere a person will read. Returning
the raw id there produces output like ``source:7``, which is the failure
mode the central helper exists to prevent.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from yoke_core.domain import db_backend

SYSTEM_COMPONENT_YOKE_CORE = "yoke-core"

#: Env var that injects the local human actor's name into canonical-actor
#: seeding. The environment-bootstrap init chain invokes each init module
#: as ``main(["init"])`` with no parameters, so per-universe context rides
#: pinned env vars (the same idiom as the ``YOKE_PG_DSN`` authority pin);
#: the local-universe birth path pins this to the OS login so a fresh
#: machine-local universe names its human actor after its actual owner.
#: Naming a row being created is not identity selection — nothing later
#: reads this value back to decide which actor a caller is.
LOCAL_HUMAN_NAME_ENV = "YOKE_LOCAL_HUMAN_NAME"

#: Name given to a brand-new local universe's human actor when neither an
#: explicit name nor the env injection supplies one.
DEFAULT_LOCAL_HUMAN_NAME = "ben"


class ActorError(Exception):
    """Base class for actor-resolution failures."""


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

    Returns the actor id. The system actor's name is its component token:
    a system actor has no person behind it, so the component name is both
    what it is and what to call it. The partial UNIQUE index on
    ``actors.system_component`` (``WHERE system_component IS NOT NULL``)
    cannot be referenced by ``ON CONFLICT`` because SQLite does not
    consider partial indexes as conflict targets, so the helper SELECTs
    first and only INSERTs on a miss.
    """
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT id FROM actors WHERE system_component = {p}",
        (system_component,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cur = conn.execute(
        "INSERT INTO actors (kind, system_component, name, created_at) "
        f"VALUES ('system', {p}, {p}, {p}) RETURNING id",
        (system_component, system_component, _now()),
    )
    actor_id = int(cur.fetchone()[0])
    conn.commit()
    return actor_id


def seed_human_actor(conn: Any, name: str = "") -> int:
    """Insert a new human actor row and return its id.

    Human actors are not de-duplicated by any column, name included; the
    caller decides identity. ``name`` is what to call the new person and
    may be blank, shared with an existing actor, or changed later.
    """
    p = _placeholder(conn)
    cur = conn.execute(
        "INSERT INTO actors (kind, system_component, name, created_at) "
        f"VALUES ('human', NULL, {p}, {p}) RETURNING id",
        (str(name or "").strip(), _now()),
    )
    actor_id = int(cur.fetchone()[0])
    conn.commit()
    return actor_id


def actor_name(conn: Any, actor_id: int) -> str:
    """Render an actor id to its human-readable name.

    Fail-closed central helper: callers MUST go through this rather than
    reading ``actors.name`` ad hoc, so the one place that turns a numeric
    id into a person's name is the one place that refuses on a missing
    actor.

    Raises:
        ActorNotFound: the actor id does not exist.
    """
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT name FROM actors WHERE id = {p}",
        (int(actor_id),),
    ).fetchone()
    if row is None:
        raise ActorNotFound(f"actor id {actor_id} does not exist")
    return str(row[0] or "")


def actor_display_labels(
    conn: Any,
    actor_ids: Iterable[int],
) -> dict[int, str]:
    """Render actor ids distinctly when two actors share one name."""
    ids = tuple(sorted({int(value) for value in actor_ids}))
    labels: dict[int, str] = {}
    for actor_id in ids:
        try:
            label = actor_name(conn, actor_id).strip()
        except ActorError:
            label = ""
        labels[actor_id] = label or f"actor {actor_id}"
    values = tuple(labels.values())
    counts = {label: values.count(label) for label in values}
    return {
        actor_id: label if counts[label] == 1 else f"{label} (actor {actor_id})"
        for actor_id, label in labels.items()
    }


def is_human_actor(conn: Any, actor_id: int) -> bool:
    """Return whether an actor id names an existing human actor."""
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {p} AND kind = 'human'",
        (int(actor_id),),
    ).fetchone()
    return row is not None


def set_actor_name(conn: Any, actor_id: int, name: Any) -> bool:
    """Set an actor's name; report whether it changed.

    The account system that owns a person's name is the authority for
    it, so this overwrites whatever the actor currently carries. A
    renamed account therefore propagates on its next sync instead of
    pinning the name it first signed in under, and because nothing
    resolves an actor from a name, the rename moves no authority: the
    same ``actors.id`` keeps its sessions, claims, roles, tokens, and
    linked external identities.

    A blank or missing name writes nothing and returns ``False``: an
    account with no name of its own leaves the actor's existing name
    exactly as it was. This never invents a name and never blanks one.

    Returns whether the stored name now differs from before, so a caller
    can report an actual rename rather than every sync.
    """
    cleaned = str(name or "").strip()
    if not cleaned:
        return False
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT name FROM actors WHERE id = {p}",
        (int(actor_id),),
    ).fetchone()
    if row is None:
        raise ActorNotFound(f"actor id {actor_id} does not exist")
    if str(row[0] or "") == cleaned:
        return False
    conn.execute(
        f"UPDATE actors SET name = {p} WHERE id = {p}",
        (cleaned, int(actor_id)),
    )
    conn.commit()
    return True


def resolve_actors_by_name(
    conn: Any,
    name: str,
    *,
    kind: Optional[str] = None,
) -> List[int]:
    """Every actor id called ``name``, in id order — an operator search.

    Returns a list rather than an id precisely so no caller can mistake
    it for identity resolution. Names are neither unique nor stable, so
    a single-element result is a coincidence of the current data and not
    a guarantee: a caller acting on the answer must handle the empty and
    multiple cases explicitly, and must never use it to choose a session
    identity, an authenticated actor, or an owner.
    """
    cleaned = str(name or "").strip()
    if not cleaned:
        return []
    p = _placeholder(conn)
    sql = f"SELECT id FROM actors WHERE name = {p}"
    params: tuple[Any, ...] = (cleaned,)
    if kind is not None:
        sql += f" AND kind = {p}"
        params += (kind,)
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    return [int(row[0]) for row in rows]


def seed_canonical_actors(
    conn: Any,
    *,
    local_human_name: Optional[str] = None,
) -> tuple[int, int]:
    """Seed the two actors every Yoke install needs and return their ids.

    Returns ``(yoke_core_id, local_human_id)``. Idempotent: a universe
    that already carries a human actor keeps it, whatever it is called.
    Re-seeding deliberately does not look the human up by name — a
    universe whose owner has since been renamed would otherwise gain a
    second human actor, and the first one holds every claim, role, and
    session already recorded.

    The new human's name resolves explicit argument first, then the
    :data:`LOCAL_HUMAN_NAME_ENV` injection (how the no-argument init
    chain passes the universe owner's OS login through), then
    :data:`DEFAULT_LOCAL_HUMAN_NAME`.
    """
    yoke_core = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    existing = sole_human_actor_id(conn, oldest=True)
    if existing is not None:
        return yoke_core, existing
    name = (
        local_human_name
        or os.environ.get(LOCAL_HUMAN_NAME_ENV, "").strip()
        or DEFAULT_LOCAL_HUMAN_NAME
    )
    return yoke_core, seed_human_actor(conn, name)


def sole_human_actor_id(conn: Any, *, oldest: bool = False) -> Optional[int]:
    """The universe's human actor, or ``None``.

    With ``oldest=False`` this answers only for a universe that carries
    exactly one human — the shape a machine-local universe has by
    construction and a multi-person control plane does not. With
    ``oldest=True`` it returns the lowest-id human whatever the count,
    which is what a seeding path wants: "is there already somebody here
    to keep?" rather than "who is the operator?".
    """
    rows = conn.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 2"
    ).fetchall()
    if not rows:
        return None
    if oldest or len(rows) == 1:
        return int(rows[0][0])
    return None


def actor_name_or_passthrough(conn: Any, value: str) -> str:
    """Render a column-stored actor token to a name, with a text passthrough.

    ``items.source`` and ``items.owner`` are text columns that hold a
    stringified ``actors.id`` on every row the current write path
    produced, and a legacy free-text token such as ``ben`` or
    ``skill-simulate`` on rows untouched since actors were introduced.
    Numeric values resolve through :func:`actor_name` and inherit its
    fail-closed contract; non-numeric values are returned unchanged so
    those older rows still render something a person can read.

    Empty / null sentinels (``""``, ``"null"``, ``"None"``) collapse to
    the empty string so callers can rely on the "render only when
    truthy" pattern they already use for other categories.
    """
    if not value or value in ("null", "None"):
        return ""
    try:
        actor_id = int(value)
    except ValueError:
        return value
    return actor_name(conn, actor_id)


def validate_actor_id(conn: Any, actor_id: int) -> bool:
    """Return True iff ``actor_id`` references an existing row."""
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {p}",
        (int(actor_id),),
    ).fetchone()
    return row is not None


__all__ = [
    "ActorError",
    "ActorNotFound",
    "DEFAULT_LOCAL_HUMAN_NAME",
    "LOCAL_HUMAN_NAME_ENV",
    "SYSTEM_COMPONENT_YOKE_CORE",
    "actor_display_labels",
    "actor_name",
    "actor_name_or_passthrough",
    "is_human_actor",
    "resolve_actors_by_name",
    "seed_canonical_actors",
    "seed_human_actor",
    "seed_system_actor",
    "set_actor_name",
    "sole_human_actor_id",
    "validate_actor_id",
]
