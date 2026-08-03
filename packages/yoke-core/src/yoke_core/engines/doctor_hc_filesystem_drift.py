"""Filesystem health check — stray root-level project output directories.

HC function: HC-stray-project-files.
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
