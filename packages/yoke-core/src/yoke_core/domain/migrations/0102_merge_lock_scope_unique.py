"""Keep one merge lock per project target."""

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn: Any) -> None:
    if not _table_exists(conn, "merge_locks"):
        return
    conn.execute(
        "DELETE FROM merge_locks WHERE project_slug IS NOT NULL "
        "AND target_branch IS NOT NULL AND id NOT IN "
        "(SELECT MIN(id) FROM merge_locks GROUP BY project_slug, target_branch)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_merge_locks_scope "
        "ON merge_locks(project_slug, target_branch)"
    )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "merge_locks"):
        return
    assert not conn.execute(
        "SELECT project_slug, target_branch FROM merge_locks "
        "WHERE project_slug IS NOT NULL AND target_branch IS NOT NULL "
        "GROUP BY project_slug, target_branch HAVING COUNT(*) > 1"
    ).fetchall()
