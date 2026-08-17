"""Reject test-shaped basenames in the shipped core runtime namespace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks._declare import self_project_checks


HC_SLUG = "runtime-module-names"
HC_NAME = "Runtime module names"
CORE_RUNTIME_ROOT = "packages/yoke-core/src/yoke_core"
NON_RUNTIME_PARTS = frozenset({"build", "dist", "install_bundle_tree", "tests"})


@dataclass(frozen=True)
class RuntimeModuleNameFinding:
    """One shipped module whose basename can be mistaken for a test."""

    relpath: str


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def scan_runtime_module_names(
    repo_root: Path,
    *,
    runtime_root: str = CORE_RUNTIME_ROOT,
) -> List[RuntimeModuleNameFinding]:
    """Find test-shaped Python basenames outside structural test surfaces."""
    base = repo_root / runtime_root
    if not base.is_dir():
        return []
    findings: List[RuntimeModuleNameFinding] = []
    for path in sorted(base.rglob("test_*.py")):
        relative_to_runtime = path.relative_to(base)
        if NON_RUNTIME_PARTS.intersection(relative_to_runtime.parts):
            continue
        findings.append(
            RuntimeModuleNameFinding(
                relpath=path.relative_to(repo_root).as_posix(),
            )
        )
    return findings


def hc_runtime_module_names(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Shipped core modules cannot use pytest-shaped basenames."""
    findings = scan_runtime_module_names(_project_root())
    if not findings:
        rec.record(
            f"HC-{HC_SLUG}",
            HC_NAME,
            "PASS",
            "Every shipped core module has a non-test basename.",
        )
        return
    detail = "\n".join(
        f"- `{finding.relpath}` is a shipped module named like a test"
        for finding in findings
    )
    rec.record(f"HC-{HC_SLUG}", HC_NAME, "FAIL", detail)


PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG, HC_NAME, hc_runtime_module_names),
)


__all__ = [
    "PROJECT_HEALTH_CHECKS",
    "RuntimeModuleNameFinding",
    "hc_runtime_module_names",
    "scan_runtime_module_names",
]
