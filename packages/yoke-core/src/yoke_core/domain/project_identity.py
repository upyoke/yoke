"""Project identity helpers for the cloud-runtime numeric-project cutover.

``projects.id`` is the database authority. ``projects.slug`` names project
context. Item public references are project-scoped
``projects.public_item_prefix`` + ``items.project_sequence``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Collection, Optional, Union

from yoke_core.domain import machine_config
from yoke_core.domain.db_backend import connection_is_postgres

# Pure item-ref formatting moved to the shipped yoke_contracts.item_ref tier
# (so the board render ships core-free); re-exported here for existing callers.
from yoke_contracts.item_ref import (  # noqa: F401
    DEFAULT_PUBLIC_ITEM_PREFIX,
    format_item_ref,
)


DEFAULT_PROJECT_SLUG = "yoke"

_PUBLIC_REF_RE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9]*)-(?P<seq>\d+)$")


@dataclass(frozen=True)
class ProjectIdentity:
    id: int
    slug: str
    name: str
    public_item_prefix: str


class AmbiguousProjectRefError(LookupError):
    """Raised when a slug names more than one project in the resolution scope."""


def placeholder(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        return row[index]


def fallback_project_slug() -> str:
    return DEFAULT_PROJECT_SLUG


def checkout_project_context() -> Union[str, int]:
    project_id = machine_config.project_id(Path.cwd())
    if project_id is not None:
        return project_id
    return fallback_project_slug()


def _row_to_identity(row: Any) -> ProjectIdentity:
    return ProjectIdentity(
        id=int(row_value(row, "id", 0)),
        slug=str(row_value(row, "slug", 1)),
        name=str(row_value(row, "name", 2)),
        public_item_prefix=str(row_value(row, "public_item_prefix", 3) or DEFAULT_PUBLIC_ITEM_PREFIX),
    )


def _visible_set(project_ids: Optional[Collection[int]]) -> Optional[set[int]]:
    if project_ids is None:
        return None
    return {int(project_id) for project_id in project_ids}


def _org_id_for_filter(conn: Any, org: Optional[Union[str, int]]) -> Optional[int]:
    if org is None:
        return None
    cleaned = str(org).strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)
    from yoke_core.domain.org_schema import org_id_by_slug

    return org_id_by_slug(conn, cleaned)


def _query_project_rows(
    conn: Any,
    raw: Union[str, int],
    *,
    org: Optional[Union[str, int]],
) -> list[Any]:
    p = placeholder(conn)
    params: list[Any]
    if isinstance(raw, int) or str(raw).isdigit():
        sql = f"SELECT id, slug, name, public_item_prefix FROM projects WHERE id = {p}"
        params = [int(raw)]
    else:
        sql = (
            "SELECT id, slug, name, public_item_prefix FROM projects "
            f"WHERE slug = {p}"
        )
        params = [str(raw)]
    org_id = _org_id_for_filter(conn, org)
    if org_id is not None:
        sql += f" AND org_id = {p}"
        params.append(org_id)
    return list(conn.execute(sql + " ORDER BY id", tuple(params)).fetchall())


def resolve_project(
    conn: Any,
    project: Optional[Union[str, int]] = None,
    *,
    required: bool = True,
    visible_project_ids: Optional[Collection[int]] = None,
    org: Optional[Union[str, int]] = None,
) -> Optional[ProjectIdentity]:
    """Resolve a slug or numeric id into one canonical project row.

    ``projects.id`` is authority. A slug is shorthand only inside a concrete
    resolution scope: an org filter, an actor-visible project set, or the
    historical single-match local context. If the scoped slug still matches more
    than one project, callers must pass a numeric id or narrow by org.
    """
    raw = checkout_project_context() if project is None else project
    rows = _query_project_rows(conn, raw, org=org)
    visible = _visible_set(visible_project_ids)
    if visible is not None:
        rows = [row for row in rows if int(row_value(row, "id", 0)) in visible]
    if not rows:
        if required:
            raise LookupError(f"project {raw!r} not found")
        return None
    if len(rows) > 1:
        ids = ", ".join(str(row_value(row, "id", 0)) for row in rows)
        raise AmbiguousProjectRefError(
            f"project {raw!r} is ambiguous across project ids: {ids}; "
            "use a numeric project id or narrow by org"
        )
    return _row_to_identity(rows[0])


def resolve_project_id(
    conn: Any,
    project: Optional[Union[str, int]] = None,
    *,
    visible_project_ids: Optional[Collection[int]] = None,
    org: Optional[Union[str, int]] = None,
) -> int:
    ident = resolve_project(
        conn, project, required=True,
        visible_project_ids=visible_project_ids,
        org=org,
    )
    assert ident is not None
    return ident.id


def resolve_project_slug(conn: Any, project_id: int) -> str:
    p = placeholder(conn)
    row = conn.execute(f"SELECT slug FROM projects WHERE id = {p}", (project_id,)).fetchone()
    if row is None:
        raise LookupError(f"project id {project_id} not found")
    return str(row_value(row, "slug", 0))


def resolve_project_for_public_prefix(
    conn: Any,
    public_item_prefix: str,
    *,
    required: bool = True,
) -> Optional[ProjectIdentity]:
    """Resolve a public item prefix to exactly one project."""

    prefix = str(public_item_prefix or "").strip().upper()
    if not prefix:
        if required:
            raise LookupError("public item prefix is empty")
        return None
    p = placeholder(conn)
    rows = conn.execute(
        f"""SELECT id, slug, name, public_item_prefix FROM projects
            WHERE UPPER(public_item_prefix) = {p}
            ORDER BY id""",
        (prefix,),
    ).fetchall()
    if not rows:
        if required:
            raise LookupError(f"public item prefix {prefix!r} not found")
        return None
    if len(rows) > 1:
        slugs = ", ".join(str(row_value(row, "slug", 1)) for row in rows)
        raise LookupError(
            f"public item prefix {prefix!r} is shared by projects: {slugs}"
        )
    return _row_to_identity(rows[0])


def allocate_project_sequence(conn: Any, project_id: int) -> int:
    """Return the next per-project sequence: one past the project's current max.

    A per-project reference number is a monotonic handle (like a GitHub issue
    number) — it never reuses a gap left by a deleted item and never collides
    backward into already-issued numbers. The cloud-runtime cutover backfilled existing
    rows with ``project_sequence = items.id``, leaving each project's used
    sequences as a high, gap-pocked band. A smallest-unused-from-1 allocator
    would hand the next item sequence ``1``
    — colliding backward into number space that conceptually predates every
    issued reference. Continuing from ``MAX(project_sequence) + 1`` keeps
    new numbers strictly ahead of every reference already issued in the project.
    """
    p = placeholder(conn)
    row = conn.execute(
        f"SELECT MAX(project_sequence) AS max_seq FROM items WHERE project_id = {p}",
        (project_id,),
    ).fetchone()
    current_max = row_value(row, "max_seq", 0) if row is not None else None
    return int(current_max) + 1 if current_max is not None else 1


def resolve_item_id(
    conn: Any,
    raw_ref: str | int,
    *,
    project: Optional[Union[str, int]] = None,
) -> Optional[int]:
    """Resolve ``PREFIX-N`` or project-context bare sequence to internal id."""
    if isinstance(raw_ref, int):
        return raw_ref
    text = str(raw_ref).strip()
    if text.isdigit():
        if project is None:
            return None
        ident = resolve_project(conn, project, required=True)
        sequence = int(text.lstrip("0") or "0")
    else:
        match = _PUBLIC_REF_RE.match(text)
        if not match:
            return None
        prefix = match.group("prefix").upper()
        sequence = int(match.group("seq").lstrip("0") or "0")
        ident = resolve_project_for_public_prefix(conn, prefix, required=True)
    assert ident is not None
    p = placeholder(conn)
    row = conn.execute(
        f"""SELECT id FROM items
            WHERE project_id = {p} AND project_sequence = {p}""",
        (ident.id, sequence),
    ).fetchone()
    if row is None:
        return None
    return int(row_value(row, "id", 0))


def render_item_ref(
    conn: Any,
    item_id: int,
    *,
    qualify: bool = False,
) -> str:
    del qualify
    p = placeholder(conn)
    row = conn.execute(
        f"""SELECT p.slug, p.public_item_prefix, i.project_sequence
            FROM items i
            JOIN projects p ON p.id = i.project_id
            WHERE i.id = {p}""",
        (item_id,),
    ).fetchone()
    if row is None:
        return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{item_id}"
    prefix = row_value(row, "public_item_prefix", 1)
    sequence = row_value(row, "project_sequence", 2)
    return format_item_ref(
        row_value(row, "slug", 0),
        prefix,
        sequence,
        item_id=item_id,
    )


# format_item_ref relocated to yoke_contracts.item_ref (re-exported above).


def item_project_join_select(
    fields: list[str],
    *,
    item_alias: str = "i",
) -> tuple[str, bool]:
    """Build SELECT columns, mapping public ``project`` to ``projects.slug``."""
    needs_project = "project" in fields
    parts: list[str] = []
    for field in fields:
        if field == "project":
            parts.append("COALESCE(CAST(p.slug AS TEXT), '') AS project")
        else:
            parts.append(f"COALESCE(CAST({item_alias}.{field} AS TEXT), '') AS {field}")
    return ", ".join(parts), needs_project


__all__ = [
    "AmbiguousProjectRefError",
    "DEFAULT_PROJECT_SLUG",
    "DEFAULT_PUBLIC_ITEM_PREFIX",
    "ProjectIdentity",
    "allocate_project_sequence",
    "checkout_project_context",
    "fallback_project_slug",
    "format_item_ref",
    "item_project_join_select",
    "placeholder",
    "render_item_ref",
    "resolve_item_id",
    "resolve_project",
    "resolve_project_for_public_prefix",
    "resolve_project_id",
    "resolve_project_slug",
    "row_value",
]
