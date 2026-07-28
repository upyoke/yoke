"""Target-kind and per-task coverage helpers for the commit guard."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists


Target = tuple[str, str]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def declared_targets_for_claim(
    conn: Any,
    claim_id: int,
) -> tuple[list[str], list[Target]]:
    """Read paths and optional kinds from legacy or current fixtures."""
    has_target_kind = _column_exists(conn, "path_targets", "kind")
    kind_projection = ", pt.kind" if has_target_kind else ""
    rows = conn.execute(
        f"SELECT pt.path_string{kind_projection} "
        "FROM path_claim_targets pct "
        "JOIN path_targets pt ON pt.id = pct.target_id "
        f"WHERE pct.claim_id = {_p(conn)} "
        "ORDER BY pct.id",
        (claim_id,),
    ).fetchall()
    paths = [
        str(row["path_string"] if hasattr(row, "keys") else row[0]) for row in rows
    ]
    if not has_target_kind:
        return paths, []
    return paths, [
        (
            str(row["path_string"] if hasattr(row, "keys") else row[0]),
            str(row["kind"] if hasattr(row, "keys") else row[1]),
        )
        for row in rows
    ]


def effective_commit_targets(
    conn: Any,
    *,
    session_id: str,
    item_id: int,
    repo_root: Path,
    declared_paths: Sequence[str],
    declared_target_kinds: Sequence[Target],
) -> tuple[list[str], list[Target]]:
    """Narrow parent claim targets to the committing session's lane."""
    try:
        from yoke_core.domain.path_claim_task_bindings import (
            pinned_task_claim_policy,
        )

        task_scoped = pinned_task_claim_policy(conn, item_id)
    except Exception:
        task_scoped = True
    if not task_scoped:
        return list(declared_paths), list(declared_target_kinds)
    try:
        from yoke_core.domain.path_claim_task_session_coverage import (
            effective_targets_for_session,
        )

        targets = list(
            effective_targets_for_session(
                conn,
                session_id=session_id,
                item_id=item_id,
                target_path="",
                cwd=str(repo_root),
            )
        )
    except Exception:
        targets = []
    return [path for path, _kind in targets], targets


__all__ = ["declared_targets_for_claim", "effective_commit_targets"]
