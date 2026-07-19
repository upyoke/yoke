"""Filesystem health checks — stray files and architecture consistency.

Cluster: HC checks for stray root-level project files and schema completeness.

HC functions: HC-stray-project-files, HC-arch-consistency.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_stray_project_files(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stray-project-files: Stray root-level project output directories."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-stray-project-files", "Stray project output directories", "PASS", "")
        return

    repo = Path(repo_root)
    issues: List[str] = []

    # Check for old root-level project-specific output directories.
    stray_patterns = [
        (repo / "deployments", "deployments/"),
        (repo / "workflows", "workflows/"),
    ]
    for path, label in stray_patterns:
        if path.is_dir():
            issues.append(
                f"- {label} exists at repo root -- render project outputs to "
                "the managed project repo or scratch/deploy-run output"
            )

    if issues:
        rec.record("HC-stray-project-files", "Stray project output directories", "FAIL",
                    "\n".join(issues))
    else:
        rec.record("HC-stray-project-files", "Stray project output directories", "PASS", "")

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
