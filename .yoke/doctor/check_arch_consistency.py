"""HC-arch-consistency — retired layout and schema surfaces in this repo.

Flags a retired root state directory in the Yoke checkout and missing
Yoke-specific tables (ouroboros log, wrapup reports, epic task metadata).
Both halves describe this project's own architecture, not any project the
engine is pointed at.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_arch_consistency(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-arch-consistency: Architectural consistency audit."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-arch-consistency", "Architectural consistency audit", "PASS", "")
        return

    issues: List[str] = []

    # Pattern 2: Retired root state dir
    if (Path(repo_root) / "data").exists():
        issues.append("- Retired root data directory still exists: data/")

    # Pattern 4: Schema completeness
    for tbl_name, label in [
        ("ouroboros_entries", "ouroboros log"),
        ("wrapup_reports", "wrapup reports"),
        ("epic_tasks", "epic task metadata"),
    ]:
        if not _base._table_exists(conn, tbl_name):
            issues.append(f"- Schema gap: '{tbl_name}' table missing")

    if issues:
        rec.record("HC-arch-consistency", "Architectural consistency audit", "WARN", "\n".join(issues))
    else:
        rec.record("HC-arch-consistency", "Architectural consistency audit", "PASS", "")


__all__ = ["hc_arch_consistency"]

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('arch-consistency', 'Architectural consistency audit', hc_arch_consistency),
)
