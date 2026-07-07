"""Doctor HC: installer live-TUI machinery stays leaf-only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, List

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-installer-live-tui-import-boundary"
HC_DESC = (
    "App code must not import the interim installer live-TUI harness machinery"
)

SCAN_ROOTS = ("packages", "runtime")
FAMILY_BASENAME_PREFIX = "installer_live_tui_"
FAMILY_TEST_RE = re.compile(r"runtime/api/tools/test_installer_live_tui_.*\.py$")
IMPORT_RE = re.compile(
    r"^\s*(?:"
    r"from\s+yoke_core\.tools\.installer_live_tui_[A-Za-z0-9_]*\s+import\b"
    r"|from\s+yoke_core\.tools\s+import\s+.*\binstaller_live_tui_[A-Za-z0-9_]*\b"
    r"|import\s+yoke_core\.tools\.installer_live_tui_[A-Za-z0-9_]*\b"
    r")"
)


@dataclass(frozen=True)
class InstallerLiveTuiImportFinding:
    relpath: str
    line_no: int
    line: str


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _relpath(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_python_files(repo_root: Path) -> Iterable[Path]:
    for rel in SCAN_ROOTS:
        base = repo_root / rel
        if not base.is_dir():
            continue
        yield from sorted(base.rglob("*.py"))


def _skip_path(repo_root: Path, path: Path) -> bool:
    if path.name.startswith(FAMILY_BASENAME_PREFIX):
        return True
    return bool(FAMILY_TEST_RE.search(_relpath(repo_root, path)))


def scan_installer_live_tui_import_boundary(
    repo_root: Path,
) -> List[InstallerLiveTuiImportFinding]:
    """Return imports that would entangle the installer harness with app code."""
    findings: List[InstallerLiveTuiImportFinding] = []
    for path in _iter_python_files(repo_root):
        if _skip_path(repo_root, path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        relpath = _relpath(repo_root, path)
        for line_no, line in enumerate(lines, start=1):
            if IMPORT_RE.search(line):
                findings.append(
                    InstallerLiveTuiImportFinding(
                        relpath=relpath,
                        line_no=line_no,
                        line=line.strip(),
                    )
                )
    return findings


def hc_installer_live_tui_import_boundary(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Doctor entry. FAILs if non-harness code imports installer live-TUI tools."""
    del conn, args
    findings = scan_installer_live_tui_import_boundary(_project_root())
    if not findings:
        rec.record(
            HC_NAME,
            HC_DESC,
            "PASS",
            "No non-harness Python module imports installer_live_tui_* tools.",
        )
        return
    head = (
        f"- {len(findings)} Python import(s) entangle app code with the interim "
        "installer live-TUI harness. Keep the harness leaf-only until it is "
        "removed or extracted."
    )
    body = "\n".join(
        [head, ""]
        + [
            f"  - `{f.relpath}:{f.line_no}` {f.line}"
            for f in findings
        ]
    )
    rec.record(HC_NAME, HC_DESC, "FAIL", body)


__all__ = [
    "HC_NAME",
    "HC_DESC",
    "FAMILY_TEST_RE",
    "IMPORT_RE",
    "InstallerLiveTuiImportFinding",
    "hc_installer_live_tui_import_boundary",
    "scan_installer_live_tui_import_boundary",
]
