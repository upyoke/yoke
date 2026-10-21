"""The project context a snapshot sync refreshes when the synced HEAD moves.

Architecture classifications and generated-file provenance derive from the
HEAD file inventory, and derived project facts are kept warm beside them.
Hooks sync the same HEAD many times between commits; re-deriving all three on
each of those repeated the same writes. The newest stored snapshot is the
last HEAD this work ran for, so a sync naming that same commit skips it.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Dict, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_derived_facts import converge_derived_facts


_LOG = logging.getLogger(__name__)


def latest_snapshot_commit(conn: Any, project_id: int) -> str:
    """The commit of the project's newest stored content snapshot, or ``""``."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT commit_sha FROM path_snapshots "
        f"WHERE project_id = {marker} ORDER BY id DESC LIMIT 1",
        (int(project_id),),
    ).fetchone()
    return str(row[0] or "") if row else ""


def head_inventory_row(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """HEAD's row when it carries a file inventory; identity-only rows do not."""
    return next(
        (r for r in rows if r.get("ref") == "HEAD" and r.get("snapshot_id")),
        None,
    )


def refresh_after_head_change(
    conn: Any,
    project_id: int,
    rows: List[Dict[str, Any]],
    warnings: List[str],
    *,
    previous_head: str,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Refresh HEAD-derived context, or nothing when HEAD has not moved."""
    head = next((r for r in rows if r.get("ref") == "HEAD"), None)
    if head is not None and str(head.get("commit_sha") or "") == previous_head:
        return {
            "architecture_refresh": None,
            "render_relationship_refresh": None,
            "derived_facts": None,
        }
    result = {}
    for step, refresh, args in (
        ("architecture_refresh", refresh_architecture_context, (conn, project_id, rows)),
        ("render_relationship_refresh", refresh_render_relationship_context,
         (conn, project_id, rows, warnings)),
        ("derived_facts", converge_derived_facts, (conn, project_id, warnings)),
    ):
        started = perf_counter()
        try:
            result[step] = refresh(*args)
        finally:
            _LOG.info(
                "snapshot_head_refresh project_id=%s step=%s duration_ms=%.3f",
                project_id, step, (perf_counter() - started) * 1000,
            )
    return result


def refresh_architecture_context(
    conn: Any,
    project_id: int,
    rows: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Converge map-derived classifications after a HEAD snapshot lands.

    Classifications derive from the map plus the tree, so they refresh
    whenever the file inventory does. Projects without a declared map
    skip silently; the synced commit is the provenance token.
    """
    head = head_inventory_row(rows)
    if head is None:
        return None
    from yoke_core.domain.architecture_path_context_seed import (
        seed_architecture_path_context,
    )

    seed = seed_architecture_path_context(
        conn,
        project_id,
        recorded_event_id=f"snapshot:{head.get('commit_sha') or 'HEAD'}",
    )
    if not seed.declared:
        return None
    return {
        "layer_rows": seed.layer_rows,
        "domain_rows": seed.domain_rows,
        "exemption_rows": seed.exemption_rows,
        "unclassified": seed.unclassified,
        "removed_rows": seed.removed_rows,
        "operator_rows_kept": seed.operator_rows_kept,
    }


def refresh_render_relationship_context(
    conn: Any,
    project_id: int,
    rows: List[Dict[str, Any]],
    warnings: List[str],
) -> Optional[Dict[str, Any]]:
    """Refresh the project's generated-file provenance after a HEAD snapshot.

    Relationships derive from the project's own tracked paths, so a project
    with no generated outputs records none.
    """
    if head_inventory_row(rows) is None:
        return None
    from yoke_core.domain.project_identity import resolve_project_slug

    project_slug = resolve_project_slug(conn, project_id)
    try:
        from yoke_core.domain.agents_render_path_context import (
            record_render_relationships,
        )

        written = record_render_relationships(conn, project_id=project_slug)
    except Exception as exc:
        warnings.append(
            "generated-file render relationship refresh was advisory and "
            f"did not complete: {exc}"
        )
        return {"status": "degraded", "written": 0}
    return {"status": "ok", "written": written}


__all__ = [
    "head_inventory_row",
    "latest_snapshot_commit",
    "refresh_after_head_change",
    "refresh_architecture_context",
    "refresh_render_relationship_context",
]
