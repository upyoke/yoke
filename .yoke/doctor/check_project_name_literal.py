"""HC-project-name-literal: product code never branches on a literal project name.

Delegates to :mod:`yoke_core.domain.lint_project_name_literal`, scanning for the
registered project names this installation actually holds. An unallowed hit or
a stale allowance FAILs with its location and the recovery; a pending site
(a branch whose replacement is in flight) WARNs so it stays visible.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.lint_project_name_literal import RECOVERY, scan, source_paths
from yoke_core.domain.lint_project_name_literal_allowances import classify
from yoke_core.engines.doctor_parallel_reads import prefetched_text_reader
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
    _table_exists,
)

_SLUG = "HC-project-name-literal"
_TITLE = "Product code never branches on a literal project name"


def _project_names(conn) -> frozenset:
    if conn is None or not _table_exists(conn, "projects"):
        return frozenset()
    return frozenset(
        str(row[0]) for row in query_rows(conn, "SELECT slug FROM projects")
    )


def hc_project_name_literal(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Product code never branches on a literal project name."""
    del args
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(
            _SLUG,
            _TITLE,
            "N/A",
            "scans the product source tree; this runner resolved no repo root",
        )
        return
    repo_root = Path(repo_root_str).resolve()
    read_text = prefetched_text_reader(source_paths(repo_root))
    hits = scan(repo_root, project_names=_project_names(conn), read_text=read_text)
    violations, pending, stale = classify(hits)
    lines = [f"- {hit.relpath}:{hit.line}: {hit.snippet}" for hit in violations]
    lines += [
        f"- stale allowance {a.relpath} ({a.subject}): no longer matches; remove it"
        for a in stale
    ]
    if lines:
        rec.record(
            _SLUG,
            _TITLE,
            "FAIL",
            "project_name_literal_branch: product code binds or compares a "
            f"literal project name ({len(lines)} finding(s)).\n"
            + "\n".join(lines)
            + f"\nRecovery: {RECOVERY}",
        )
    elif pending:
        rec.record(
            _SLUG,
            _TITLE,
            "WARN",
            "project-name branches whose replacement is in flight:\n"
            + "\n".join(f"- {h.relpath}:{h.line}: {h.snippet}" for h in pending),
        )
    else:
        rec.record(_SLUG, _TITLE, "PASS", "")


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ("project-name-literal", _TITLE, hc_project_name_literal),
)
