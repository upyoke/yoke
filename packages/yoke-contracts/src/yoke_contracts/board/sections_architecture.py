"""Architecture-health board section.

One line per project that declares an architecture map: classification
coverage over the latest snapshot's Python files, computed with the
same inherited-context semantics the health computer uses. Projects
without a declared map are omitted, and the whole section collapses
when nothing in scope declares one — terminal-only installs see the
same numbers the dashboard serves. Violation detail needs the model
payload plus module resolution, so the section points at the health
read instead of restating it.
"""

from __future__ import annotations

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_filter

from yoke_contracts.board.architecture_data import render_architecture_rows

_CONTEXT_FAMILIES = (
    "'architecture_layer','architecture_domain',"
    "'architecture_generated','architecture_fixture',"
    "'architecture_archive','architecture_test_surface',"
    "'architecture_pack_source'"
)


def _coverage_sql(project_id: int) -> str:
    return (
        "WITH RECURSIVE "
        f"latest AS (SELECT id FROM path_snapshots WHERE project_id = "
        f"{int(project_id)} ORDER BY id DESC LIMIT 1), "
        "py AS (SELECT pse.target_id FROM path_snapshot_entries pse "
        "JOIN latest ON pse.snapshot_id = latest.id "
        "WHERE pse.language = 'python'), "
        "chain(target_id, ancestor_id) AS ("
        "SELECT target_id, target_id FROM py "
        "UNION ALL "
        "SELECT chain.target_id, pt.parent_target_id FROM chain "
        "JOIN path_targets pt ON pt.id = chain.ancestor_id "
        "WHERE pt.parent_target_id IS NOT NULL), "
        "covered AS (SELECT DISTINCT chain.target_id FROM chain "
        "JOIN path_context_values cv ON cv.target_id = chain.ancestor_id "
        "WHERE cv.entry_key = '' "
        f"AND cv.context_family IN ({_CONTEXT_FAMILIES})) "
        "SELECT (SELECT COUNT(*) FROM py), (SELECT COUNT(*) FROM covered)"
    )


def collect_architecture_rows(db: BoardDBLike, scope: str) -> list[dict]:
    """Read coverage facts for projects with a declared architecture map."""
    scope_sql, scope_params = project_filter(scope, "ps")
    declared = db.query_quiet(
        "SELECT ps.project_id, p.slug FROM project_structure ps "
        "JOIN projects p ON p.id = ps.project_id "
        "WHERE ps.family = 'architecture_model'" + scope_sql + " ORDER BY p.slug",
        scope_params,
    )
    result = []
    for project_id, slug in declared:
        row = db.query_quiet(_coverage_sql(int(project_id)))
        total, covered = row[0] if row else (0, 0)
        result.append(
            {"project": slug, "total": int(total or 0), "covered": int(covered or 0)}
        )
    return result


def render_architecture_section(db: BoardDBLike, scope: str) -> str:
    """Render the scoped architecture coverage facts."""
    return render_architecture_rows(collect_architecture_rows(db, scope))


__all__ = ["collect_architecture_rows", "render_architecture_section"]
