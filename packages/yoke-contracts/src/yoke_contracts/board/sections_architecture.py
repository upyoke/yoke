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

from typing import List

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_filter

_ARCHITECTURE_EMOJI = "\U0001f5fa"  # 🗺

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


def render_architecture_section(db: BoardDBLike, scope: str) -> str:
    """Render the section text, or empty when no scoped map exists."""
    scope_sql, scope_params = project_filter(scope, "ps")
    declared = db.query(
        "SELECT ps.project_id, p.slug FROM project_structure ps "
        "JOIN projects p ON p.id = ps.project_id "
        "WHERE ps.family = 'architecture_model'" + scope_sql +
        " ORDER BY p.slug",
        scope_params,
    )
    if not declared:
        return ""
    lines: List[str] = [f"### {_ARCHITECTURE_EMOJI} Architecture", ""]
    for project_id, slug in declared:
        row = db.query(_coverage_sql(int(project_id)))
        total, covered = (row[0] if row else (0, 0))
        total = int(total or 0)
        covered = int(covered or 0)
        if total:
            pct = round(100.0 * covered / total, 1)
            lines.append(
                f"  {slug}: {pct}% classified · "
                f"{total - covered} unclassified of {total} python files"
            )
        else:
            lines.append(f"  {slug}: map declared · no snapshot yet")
    lines.append(
        "  violations: `yoke project-structure architecture-health get "
        "--project <slug>`"
    )
    return "\n".join(lines)


__all__ = ["render_architecture_section"]
