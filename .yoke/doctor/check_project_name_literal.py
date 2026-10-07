"""HC-project-name-literal: product code never branches on a literal project name.

Delegates to :mod:`yoke_core.domain.lint_project_name_literal`. Product code
runs for every install, so a comparison against a literal project slug makes
behavior differ for every other project. Any hit FAILs with its location and
the recovery: read the declared fact the literal stands in for.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.lint_project_name_literal import RECOVERY, scan, source_paths
from yoke_core.engines.doctor_parallel_reads import prefetched_text_reader
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

_SLUG = "HC-project-name-literal"
_TITLE = "Product code never branches on a literal project name"


def hc_project_name_literal(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Product code never branches on a literal project name."""
    del conn, args
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(_SLUG, _TITLE, "PASS", "No repo root resolved — skipping.")
        return
    repo_root = Path(repo_root_str).resolve()
    read_text = prefetched_text_reader(source_paths(repo_root))
    hits = scan(repo_root, read_text=read_text)
    if not hits:
        rec.record(_SLUG, _TITLE, "PASS", "")
        return
    lines = [f"- {hit.relpath}:{hit.line}: {hit.snippet}" for hit in hits]
    rec.record(
        _SLUG,
        _TITLE,
        "FAIL",
        "project_name_literal_branch: product code compares a project "
        f"identifier to a literal project name ({len(hits)} site(s)).\n"
        + "\n".join(lines)
        + f"\nRecovery: {RECOVERY}",
    )


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ("project-name-literal", _TITLE, hc_project_name_literal),
)
