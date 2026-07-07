"""Pre-warm a project's integration-target snapshot.

Companion to :mod:`yoke_core.domain.path_snapshots`. The base module's
``build_head_snapshot`` covers local HEAD — the SHA the operator just
committed. Activation and boundary checks, however, query the snapshot
keyed to the integration target's tip resolved *origin-then-local* (see
:mod:`yoke_core.domain.path_claims_integration_resolver`). When local
``main`` is ahead of ``origin/main`` (or a feature branch is ahead of
its base), those two SHAs differ and the warm step misses the SHA the
activation query will actually land on.

This module supplies the second half: ``ensure_integration_target_snapshot``
runs the same resolver activation uses and materialises the snapshot
row inline via ``ensure_snapshot_at``. Lives in its own module to keep
:mod:`yoke_core.domain.path_snapshots` under its line budget while
preserving the lazy import that breaks the cycle with
``path_claims_integration_resolver``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from yoke_core.domain.path_snapshots import _resolve_repo_path  # noqa: F401 — re-used
from yoke_core.domain.project_identity import resolve_project_id


def _resolve_integration_target(
    conn: Any, project_id: int
) -> str:
    """Return the project's default integration branch, falling back to 'main'.

    Reads ``projects.default_branch``. Defensive against minimal test
    fixtures that omit the column — falls back to ``"main"`` rather than
    propagating a schema error. The swallow keys off the dialect of the
    *actual* connection (Postgres raises ``psycopg.errors.UndefinedColumn``,
    SQLite raises ``sqlite3.OperationalError``); on Postgres the failed query
    leaves the transaction aborted, so it is rolled back before returning.
    """
    from yoke_core.domain import db_backend

    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT default_branch FROM projects WHERE id = {p}",
            (project_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            conn.rollback()
        return "main"
    if row is None:
        return "main"
    raw = row[0] if not hasattr(row, "keys") else row["default_branch"]
    return str(raw) if raw else "main"


def ensure_integration_target_snapshot(
    conn: Any, project_id: int | str
) -> Optional[int]:
    """Ensure a snapshot exists at the project's integration-target tip.

    Resolves the integration target via origin-then-local — the same rule
    activation and boundary checks use — so the snapshot row at that SHA
    is materialised before any downstream caller asks for it. Without
    this, ``path_snapshots --ensure-head`` only warms local HEAD; when
    local ``main`` is ahead of ``origin/main`` (or a feature branch is
    ahead of its base) the activation query lands on a SHA the warm step
    never touched.

    Returns the snapshot id, or ``None`` when neither
    ``refs/remotes/origin/<target>`` nor ``refs/heads/<target>`` exists
    (nothing to warm).

    Propagates :class:`IntegrationTargetDiverged` when origin and local
    have truly diverged; the caller's existing reconcile guidance applies.
    """
    # Lazy imports: path_snapshots imports this module from its CLI
    # path. Deferring resolves the import cycle.
    from yoke_core.domain.path_claims_boundary_git import BoundaryCheckError
    from yoke_core.domain.path_claims_integration_resolver import (
        resolve_integration_head_with_divergence_check,
    )
    from yoke_core.domain.path_snapshots import ensure_snapshot_at

    resolved_project_id = resolve_project_id(conn, project_id)
    repo_path: Path = _resolve_repo_path(conn, resolved_project_id)
    target = _resolve_integration_target(conn, resolved_project_id)
    try:
        commit_sha = resolve_integration_head_with_divergence_check(
            conn,
            project_id=str(resolved_project_id),
            repo_path=str(repo_path),
            integration_target=target,
        )
    except BoundaryCheckError:
        return None
    return ensure_snapshot_at(conn, resolved_project_id, commit_sha)


__all__ = ["ensure_integration_target_snapshot"]
