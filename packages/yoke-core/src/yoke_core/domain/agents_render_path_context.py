"""Bridge between generated-file writers and the path-context families.

Enumerates generated Yoke outputs and their safe seed sources, then registers
each output as a
:data:`yoke_core.domain.path_context.FAMILY_RENDER_TARGET` with its
seed-source list. The overlap classifier consults the resulting rows
through :func:`read_render_source_for` to recognise false-positive
overlap on deterministic rendered output.

Public surface:

- :func:`render_relationship_map` — pure data: render-target path
  string → sorted list of seed-source path strings. Read by tests and
  the integrity invariant; no DB access.
- :func:`set_render_relationship` / :func:`read_render_source_for` —
  thin wrappers around ``path_context_values`` that operate on the
  render-relationship families. Skip silently when no path_targets row
  exists for the rendered file (opportunistic registration).
- :func:`record_render_relationships` — emit one batch-level
  ``RenderRelationshipRecorded`` event and write/refresh every
  relationship row idempotently.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from yoke_core.domain.event_registry_seed_render_relationship import (
    EVENT_NAME_RENDER_RELATIONSHIP_RECORDED,
)
from yoke_core.domain.events import emit_event
from yoke_core.domain.path_context import (
    FAMILY_RENDER_SOURCE,
    FAMILY_RENDER_TARGET,
    put_context_value,
    read_context_value,
)
from yoke_core.domain.render_relationship_inventory import (
    render_relationship_map,
)


def set_render_relationship(
    conn: Any,
    *,
    target_path: str,
    source_paths: Sequence[str],
    recorded_event_id: str,
    project_id: str | int = "yoke",
) -> Optional[int]:
    """Record ``target_path`` as a render target with ``source_paths`` as seeds.

    Looks up the project-relative path_targets row for ``target_path``.
    When the row exists, writes/refreshes a single
    ``FAMILY_RENDER_TARGET`` ``path_context_values`` row with value
    ``{"sources": [...sorted seed path strings]}``. Each source that
    has its own path_targets row gets a parallel
    ``FAMILY_RENDER_SOURCE`` row keyed by the target path so the
    path-integrity invariant can detect missing target/source pairs.

    Returns the rendered target's row id on success; ``None`` when the
    target_path has no path_targets row yet (opportunistic registration).
    """
    from yoke_core.domain.path_registry import target_at

    target_id = target_at(conn, project_id, target_path)
    if target_id is None:
        return None
    normalised_sources = sorted({str(p) for p in source_paths if p})
    row_id = put_context_value(
        conn,
        target_id=target_id,
        context_family=FAMILY_RENDER_TARGET,
        entry_key="",
        value={"sources": normalised_sources},
        recorded_event_id=recorded_event_id,
    )
    for source_path in normalised_sources:
        source_target_id = target_at(conn, project_id, source_path)
        if source_target_id is None:
            continue
        put_context_value(
            conn,
            target_id=source_target_id,
            context_family=FAMILY_RENDER_SOURCE,
            entry_key=target_path,
            value={"target": target_path},
            recorded_event_id=recorded_event_id,
        )
    return row_id


def read_render_source_for(
    conn: Any, *, target_id: int,
) -> Optional[List[str]]:
    """Return the seed-source path strings registered for a render target.

    Reads the ``FAMILY_RENDER_TARGET`` row attached to ``target_id``.
    Returns ``None`` when no relationship is registered. The classifier
    consults this to decide whether overlap on the rendered file is
    provably independent at the seed-source layer.
    """
    value = read_context_value(
        conn,
        target_id=target_id,
        context_family=FAMILY_RENDER_TARGET,
        entry_key="",
    )
    if value is None:
        return None
    sources = value.get("sources") if isinstance(value, dict) else None
    if isinstance(sources, list):
        return [str(s) for s in sources if isinstance(s, str)]
    return None


def _tracked_file_paths(conn: Any, project_id: str | int) -> List[str]:
    """Return every committed file identity observed for one project."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.project_identity import resolve_project_id

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    resolved_project_id = resolve_project_id(conn, project_id)
    rows = conn.execute(
        "SELECT DISTINCT path_string FROM path_targets "
        f"WHERE project_id = {placeholder} AND kind = 'file'",
        (resolved_project_id,),
    ).fetchall()
    return sorted({str(row[0]) for row in rows})


def record_render_relationships(
    conn: Any,
    *,
    project_id: str | int = "yoke",
    session_id: str = "",
) -> int:
    """Emit one batch event and write every render relationship row.

    Returns the number of render targets that received a row (0 when no
    path_targets rows exist for any of the rendered files — the
    opportunistic case where the registry has not seen them yet). The
    emission is idempotent: existing rows are refreshed in place via
    the ``put_context_value`` upsert path.
    """
    relationships = render_relationship_map(_tracked_file_paths(conn, project_id))
    result = emit_event(
        EVENT_NAME_RENDER_RELATIONSHIP_RECORDED,
        event_kind="lifecycle",
        event_type="path_context",
        source_type="backend",
        session_id=session_id,
        project=project_id,
        context={"render_target_count": len(relationships)},
        conn=conn,
    )
    if not result.event_id:
        return 0
    written = 0
    for target_path in sorted(relationships):
        sources = relationships[target_path]
        row_id = set_render_relationship(
            conn,
            target_path=target_path,
            source_paths=sources,
            recorded_event_id=result.event_id,
            project_id=project_id,
        )
        if row_id is not None:
            written += 1
    return written


def record_render_relationships_to_canonical_db(
    *,
    db_path: Optional[str] = None,
    project_id: str | int = "yoke",
    session_id: str = "",
) -> int:
    """Register relationships on the active local or relayed control plane.

    File rendering is client-local, but ``path_context_values`` belongs to the
    control plane. A local Postgres connection writes directly; an HTTPS
    connection invokes the server-owned deterministic refresh function. The
    payload never carries caller-authored paths. Registration remains advisory:
    an unavailable or partially converged authority returns ``0`` without
    invalidating files that were rendered successfully.
    """
    try:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain import control_plane_transport
    except Exception:
        return 0

    if db_path:
        try:
            conn = connect(db_path)
        except Exception:
            return 0
    else:
        conn = control_plane_transport.local_connection_or_none(connect)

    if conn is None:
        try:
            result = control_plane_transport.relay(
                "agents.render_relationships.record",
                {"session_id": session_id},
            )
            return int(result.get("written") or 0)
        except Exception:
            return 0

    try:
        written = record_render_relationships(
            conn,
            project_id=project_id,
            session_id=session_id,
        )
        conn.commit()
        return written
    except Exception:
        return 0
    finally:
        conn.close()


__all__ = [
    "EVENT_NAME_RENDER_RELATIONSHIP_RECORDED",
    "FAMILY_RENDER_SOURCE",
    "FAMILY_RENDER_TARGET",
    "read_render_source_for",
    "record_render_relationships",
    "record_render_relationships_to_canonical_db",
    "render_relationship_map",
    "set_render_relationship",
]
