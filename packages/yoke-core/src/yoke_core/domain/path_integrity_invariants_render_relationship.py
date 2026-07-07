"""Path-integrity invariant: render-target / render-source registration honesty.

Lives separately from :mod:`yoke_core.domain.path_integrity_invariants`
so the parent module stays under its line cap. Consumed by the same
driver and surfaced through the existing ``HC-path-integrity`` doctor
check.

The invariant verifies that every ``FAMILY_RENDER_TARGET`` row points
at an in-tree rendered file AND that each of its registered seed
sources also resolves to a ``path_targets`` row in the project's
registry. A missing target file, a missing seed source row, or a stale
listed seed source surfaces as a failure so the registry stays
honest as the renderer evolves.

Three failure shapes:

* ``missing_target_file`` — the registered render target's path has no
  current-generation ``path_targets`` row; the rendered file likely
  moved or was deleted without re-running the renderer.
* ``unregistered_source`` — the value JSON lists a seed source path
  that the project's ``path_targets`` registry has not yet observed.
  Either the renderer's seed-source map drifted from the file tree
  or the registry needs a refresh.
* ``stale_target`` — a ``FAMILY_RENDER_TARGET`` row references a
  ``path_targets`` row whose path string no longer matches the
  registry's latest generation for that path string.

Each row reports the offending target_id, the rendered path, and the
specific drift reason so the operator can act without re-querying.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend


INVARIANT_RENDER_RELATIONSHIP = "render_relationship"

FailureRow = Tuple[Optional[int], dict]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_path_for_target(
    conn: Any, target_id: int
) -> Optional[str]:
    p = _p(conn)
    row = conn.execute(
        f"SELECT path_string FROM path_targets WHERE id={p}", (target_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def _registry_has_path(
    conn: Any, project_id: str, path_string: str
) -> bool:
    p = _p(conn)
    row = conn.execute(
        f"SELECT 1 FROM path_targets WHERE project_id={p} AND path_string={p} "
        "ORDER BY generation DESC LIMIT 1",
        (project_id, path_string),
    ).fetchone()
    return row is not None


def check_render_relationship(
    conn: Any, project_id: str
) -> List[FailureRow]:
    """Verify ``FAMILY_RENDER_TARGET`` rows resolve to honest registry state.

    Reads every ``FAMILY_RENDER_TARGET`` row attached to a target in
    ``project_id``. For each row, confirms:

    * The target_id resolves to a path_targets row (otherwise: stale row).
    * Every listed seed source resolves to a path_targets row in the
      same project (otherwise: ``unregistered_source``).

    The driver groups failures by (target_id, kind) so operator output
    stays scannable.
    """
    p = _p(conn)
    rows = conn.execute(
        f"""
        SELECT pcv.id, pcv.target_id, pcv.value, pt.path_string
        FROM path_context_values pcv
        LEFT JOIN path_targets pt ON pt.id = pcv.target_id
        WHERE pcv.context_family = 'render_target'
          AND (pt.project_id = {p} OR pt.project_id IS NULL)
        """,
        (project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for r in rows:
        row_id = int(r[0])
        target_id = int(r[1])
        value_text = r[2] or "{}"
        path_string = r[3]
        if path_string is None:
            failures.append((
                target_id,
                {
                    "row_id": row_id,
                    "target_id": target_id,
                    "kind": "stale_target",
                    "detail": "FAMILY_RENDER_TARGET row references a deleted "
                              "path_targets row",
                },
            ))
            continue
        if not _registry_has_path(conn, project_id, str(path_string)):
            failures.append((
                target_id,
                {
                    "row_id": row_id,
                    "target_id": target_id,
                    "kind": "missing_target_file",
                    "rendered_path": str(path_string),
                    "detail": "rendered path is not in the path_targets "
                              "registry for this project",
                },
            ))
            continue
        try:
            value = json.loads(value_text)
        except (TypeError, ValueError):
            value = {}
        sources = value.get("sources") if isinstance(value, dict) else None
        if not isinstance(sources, list):
            continue
        for src in sources:
            if not isinstance(src, str):
                continue
            if not _registry_has_path(conn, project_id, src):
                failures.append((
                    target_id,
                    {
                        "row_id": row_id,
                        "target_id": target_id,
                        "kind": "unregistered_source",
                        "rendered_path": str(path_string),
                        "missing_source": src,
                        "detail": "registered seed source is not in the "
                                  "project's path_targets registry",
                    },
                ))
    return failures


__all__ = [
    "INVARIANT_RENDER_RELATIONSHIP",
    "check_render_relationship",
]
