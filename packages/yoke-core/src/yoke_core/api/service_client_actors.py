"""Actors lookup command surface (read-only).

Exposes the actor table as a read-only lookup through the Yoke
service-client CLI, the equivalent of "GET /actors" and
"GET /actors/{id}".

Two commands:

* ``actors-list`` — JSON array of every actor row, ordered by id, with
  the generic ``display_name`` projection and the GitHub label projection
  joined when they exist. Quiet in the empty case (returns ``[]``).
* ``actors-get <id>`` — JSON object for one actor, plus the same projections.
  Exits non-zero with a ``not_found`` payload when the id has no row.

Both are read-only; mutation lives in :mod:`yoke_core.domain.actors`
and is reachable only via the seed/migration paths.
"""

from __future__ import annotations

import json
import sys

from yoke_core.domain import db_backend
from yoke_core.domain.actors import DISPLAY_LABEL_SURFACE, GITHUB_LABEL_SURFACE
from yoke_core.domain.db_helpers import connect


def _open_conn():
    """Resolve the canonical DB and open a read-only connection."""
    return connect()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_to_actor_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "kind": row["kind"],
        "system_component": row["system_component"],
        "created_at": row["created_at"],
        "display_name": row["display_name"],
        "github_label": row["github_label"],
    }


def _surface_params() -> tuple[str, str, str, str]:
    return (
        DISPLAY_LABEL_SURFACE,
        GITHUB_LABEL_SURFACE,
        DISPLAY_LABEL_SURFACE,
        GITHUB_LABEL_SURFACE,
    )


def _select_actors_sql(
    *,
    placeholder: str,
    where: str = "",
) -> str:
    return (
        "SELECT a.id, a.kind, a.system_component, a.created_at, "
        "       (SELECT label FROM actor_labels al "
        f"        WHERE al.actor_id = a.id AND al.surface = {placeholder}) AS display_label, "
        "       (SELECT label FROM actor_labels al "
        f"        WHERE al.actor_id = a.id AND al.surface = {placeholder}) AS github_label, "
        "       COALESCE("
        "           (SELECT label FROM actor_labels al "
        f"            WHERE al.actor_id = a.id AND al.surface = {placeholder}), "
        "           a.system_component, "
        "           (SELECT label FROM actor_labels al "
        f"            WHERE al.actor_id = a.id AND al.surface = {placeholder})"
        "       ) AS display_name "
        "FROM actors a "
        f"{where} "
        "ORDER BY a.id"
    )


def cmd_actors_list(args: list[str]) -> int:
    """Print every actor row as a JSON array on stdout."""
    if args:
        print("Usage: actors-list", file=sys.stderr)
        return 2
    conn = _open_conn()
    try:
        p = _p(conn)
        rows = conn.execute(
            _select_actors_sql(placeholder=p),
            _surface_params(),
        ).fetchall()
        payload = [_row_to_actor_dict(r) for r in rows]
        print(json.dumps(payload))
    finally:
        conn.close()
    return 0


def cmd_actors_get(args: list[str]) -> int:
    """Print a single actor row as a JSON object on stdout.

    Exits 1 with `{"error": "not_found", ...}` on stderr when the id
    is missing.
    """
    if len(args) != 1:
        print("Usage: actors-get <actor-id>", file=sys.stderr)
        return 2
    try:
        actor_id = int(args[0])
    except ValueError:
        print(
            json.dumps({"error": "invalid_id", "value": args[0]}),
            file=sys.stderr,
        )
        return 2
    conn = _open_conn()
    try:
        p = _p(conn)
        row = conn.execute(
            _select_actors_sql(placeholder=p, where=f"WHERE a.id = {p}"),
            (*_surface_params(), actor_id),
        ).fetchone()
        if row is None:
            print(
                json.dumps({"error": "not_found", "id": actor_id}),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(_row_to_actor_dict(row)))
    finally:
        conn.close()
    return 0


__all__ = [
    "cmd_actors_get",
    "cmd_actors_list",
]
