"""Directory walking and file discovery for the shell migration inventory.

The scanner enumerates tracked files via ``git ls-files`` (falling back to
``Path.rglob``), filters them down to the ``.sh`` set plus the textual
reference set used for caller counting, and produces lightweight per-file
metadata (path, line count, caller count). It does not classify the result —
that is the classifier's job.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

SKIP_SCAN_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".worktrees",
}

REFERENCE_SUFFIXES = {
    ".md",
    ".py",
    ".sh",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".txt",
}


def repo_root(default: Path) -> Path:
    here = default.resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists() or (candidate / "runtime" / "api").exists():
            return candidate
    return here


def is_skipped_path(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part in SKIP_SCAN_PARTS for part in parts)


def tracked_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [
            path
            for path in root.rglob("*")
            if path.is_file() and not is_skipped_path(path, root)
        ]

    files: list[Path] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = root / raw_path.decode("utf-8")
        if path.is_file() and not is_skipped_path(path, root):
            files.append(path)
    return files


def collect_text_files(root: Path, files: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for path in files:
        try:
            relpath = path.relative_to(root)
        except ValueError:
            relpath = path
        if relpath.as_posix() == "docs/archive/shell-inventory.md":
            continue
        if path.suffix.lower() in REFERENCE_SUFFIXES or path.name in {"SKILL.md", "AGENTS.md", "CLAUDE.md"}:
            out.append(path)
    return out


def count_callers(shell_paths: list[Path], text_files: Iterable[Path]) -> dict[str, int]:
    basenames = {path.name for path in shell_paths}
    callers: dict[str, set[str]] = {name: set() for name in basenames}
    for file_path in text_files:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for basename in basenames:
            if basename in text:
                callers[basename].add(str(file_path))
    return {name: max(0, len(paths) - 1) for name, paths in callers.items()}
