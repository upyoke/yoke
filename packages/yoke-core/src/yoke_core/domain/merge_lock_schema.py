"""Scoped merge lock uniqueness for fresh and converged schemas."""

SCOPE_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_merge_locks_scope "
    "ON merge_locks(project_slug, target_branch)"
)


def ensure_scope_index(conn) -> None:
    # Historical duplicate rows require the governed migration's cleanup;
    # additive boot convergence must leave those rows for that owner.
    duplicates = conn.execute(
        "SELECT 1 FROM merge_locks WHERE project_slug IS NOT NULL "
        "AND target_branch IS NOT NULL GROUP BY project_slug, target_branch "
        "HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicates is None:
        conn.execute(SCOPE_INDEX_SQL)
