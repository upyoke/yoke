"""CLI/API item-reference resolution with the bare-number project ladder.

Splits the higher-level resolver surface out of ``project_identity`` (which
owns the storage-level primitives ``resolve_item_id`` / ``resolve_project`` and
the ``_PUBLIC_REF_RE`` shape). This module layers the actor-aware, machine-aware
ladder used by CLI/API boundaries on top of those primitives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from yoke_core.domain import machine_config
from yoke_core.domain.project_identity import (
    _PUBLIC_REF_RE,
    placeholder,
    resolve_item_id,
    row_value,
)


class AmbiguousItemProjectContext(LookupError):
    """A bare item number could not be resolved to a single project."""


def _accessible_project_ids(conn: Any, actor_id: Optional[int]) -> Optional[set]:
    """Project ids the actor may access (org grants ∪ project grants).

    Returns ``None`` when no grants are recorded — an actor with no grants is
    treated as unconstrained (not-yet-restricted), not denied.
    """
    if actor_id is None:
        return None
    p = placeholder(conn)
    org = conn.execute(
        f"SELECT DISTINCT pr.id FROM projects pr "
        f"JOIN actor_org_roles aor ON aor.org_id = pr.org_id "
        f"WHERE aor.actor_id = {p}",
        (actor_id,),
    ).fetchall()
    proj = conn.execute(
        f"SELECT DISTINCT project_id FROM actor_project_roles WHERE actor_id = {p}",
        (actor_id,),
    ).fetchall()
    ids = {int(row_value(r, "id", 0)) for r in org}
    ids |= {int(row_value(r, "project_id", 0)) for r in proj}
    return ids or None


def _bare_number_project_context(
    conn: Any, *, actor_id: Optional[int], explicit: Optional[Union[str, int]]
) -> Union[str, int]:
    """Resolve which project a bare item number belongs to.

    Ladder: explicit arg -> cwd checkout -> actor-accessible set -> machine
    installed set as tiebreaker -> fail loudly. Actor access constrains every
    fallback path.
    """
    if explicit is not None:
        return explicit
    accessible = _accessible_project_ids(conn, actor_id)
    cwd_pid = machine_config.project_id(Path.cwd())
    if cwd_pid is not None and (accessible is None or cwd_pid in accessible):
        return cwd_pid
    installed = machine_config.installed_project_ids()
    if accessible is None:
        candidates = set(installed)
    else:
        candidates = (installed & accessible) or set(accessible)
    if len(candidates) == 1:
        return next(iter(candidates))
    raise AmbiguousItemProjectContext(
        "bare item number is ambiguous across projects "
        f"{sorted(candidates) if candidates else 'none'}; "
        "qualify it as PREFIX-N or slug/PREFIX-N"
    )


def resolve_cli_item_ref(
    conn: Any,
    raw: str | int,
    *,
    actor_id: Optional[int] = None,
    project_context: Optional[Union[str, int]] = None,
) -> Optional[int]:
    """Resolve a CLI/API item token to the internal ``items.id``.

    Token shapes:
    - ``slug/PREFIX-seq`` / ``slug/seq`` -> explicit project by slug
    - ``PREFIX-seq``                     -> by public prefix (self-describing)
    - bare ``seq``                       -> sequence within the project context
      resolved by the bare-number ladder
    A real ``int`` is an already-resolved internal row id (passthrough); that
    path is for internal callers, never the string boundary.
    """
    if isinstance(raw, int):
        return resolve_item_id(conn, raw)
    text = str(raw).strip()
    if not text:
        return None
    if "/" in text:
        slug, ref = text.split("/", 1)
        return resolve_item_id(conn, ref, project=slug)
    if _PUBLIC_REF_RE.match(text):
        return resolve_item_id(conn, text)
    if text.isdigit():
        project = _bare_number_project_context(
            conn, actor_id=actor_id, explicit=project_context
        )
        return resolve_item_id(conn, text, project=project)
    return None


__all__ = [
    "AmbiguousItemProjectContext",
    "resolve_cli_item_ref",
]
