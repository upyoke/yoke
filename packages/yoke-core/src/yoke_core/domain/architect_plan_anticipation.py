"""Read-only helper for Architect plan-time path anticipation."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from yoke_core.domain.architecture_dependency_scan import path_to_module

__all__ = ["AnticipationList", "build_anticipation_list"]


@dataclass(frozen=True)
class AnticipationList:
    file_budget: list[str]
    doctor_hcs: list[str]
    transitive_callers: list[str]
    test_modules: list[str]

    def all_paths(self) -> list[str]:
        return _dedupe(
            path
            for group in (
                self.file_budget,
                self.doctor_hcs,
                self.transitive_callers,
                self.test_modules,
            )
            for path in group
        )


_DEFAULT_SEARCH_ROOTS: Sequence[str] = ("runtime", "packages")
_DOCTOR_HC_DIRS: Sequence[Path] = (
    Path("runtime/api/engines"),
    Path("packages/yoke-core/src/yoke_core/engines"),
)
_SLASH = chr(47)


def _dedupe(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = str(Path(raw)) if raw else ""
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _repo_root(repo_root: Optional[Path]) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return Path(raw.strip())
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _py(paths: Iterable[str]) -> list[str]:
    return [path for path in paths if path.endswith(".py")]


def _dotted(path: str) -> str:
    rel = path.replace("\\", _SLASH)
    return path_to_module(rel)


def _doctor_hcs(repo_root: Path, file_budget: Sequence[str]) -> list[str]:
    basenames = {Path(path).stem for path in _py(file_budget)}
    if not basenames:
        return []
    hits: list[str] = []
    for hc_dir in _DOCTOR_HC_DIRS:
        for hc in sorted(repo_root.joinpath(hc_dir).glob("doctor_hc_*.py")):
            text = _read(hc)
            if any(name in text for name in basenames):
                hits.append(str(hc.relative_to(repo_root)))
    return hits


def _import_pattern(file_budget: Sequence[str]) -> Optional[re.Pattern[str]]:
    modules = sorted({_dotted(path) for path in _py(file_budget)})
    if not modules:
        return None
    names = "|".join(re.escape(module) for module in modules)
    return re.compile(
        rf"(?m)^\s*(?:from\s+(?:{names})(?:\s|\.|$)"
        rf"|import\s+(?:{names})(?:\s*,|\s+as\s|\s|\.|$))"
    )


def _python_files(repo_root: Path, search_roots: Sequence[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for rel in search_roots:
        root = repo_root.joinpath(rel)
        if root.is_dir():
            for path in root.rglob("*.py"):
                if path not in seen:
                    seen.add(path)
                    yield path


def _callers(
    repo_root: Path,
    file_budget: Sequence[str],
    search_roots: Sequence[str],
) -> list[str]:
    pattern = _import_pattern(file_budget)
    if pattern is None:
        return []
    budget = set(file_budget)
    hits: list[str] = []
    for path in _python_files(repo_root, search_roots):
        rel = str(path.relative_to(repo_root))
        if rel not in budget and pattern.search(_read(path)):
            hits.append(rel)
    return sorted(set(hits))


def build_anticipation_list(
    epic_id: int,
    task_num: int,
    file_budget_paths: list[str],
    *,
    repo_root: Optional[Path] = None,
    search_roots: Sequence[str] = _DEFAULT_SEARCH_ROOTS,
) -> AnticipationList:
    del epic_id, task_num
    root = _repo_root(repo_root)
    file_budget = _dedupe(file_budget_paths)
    callers = _callers(root, file_budget, search_roots)
    test_modules = [path for path in callers if Path(path).name.startswith("test_")]
    return AnticipationList(
        file_budget=file_budget,
        doctor_hcs=_doctor_hcs(root, file_budget),
        transitive_callers=[path for path in callers if path not in test_modules],
        test_modules=test_modules,
    )
