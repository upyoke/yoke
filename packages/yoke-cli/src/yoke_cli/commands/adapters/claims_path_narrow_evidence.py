"""Collect committed and dirty path evidence for relayed claim narrowing."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from yoke_cli.project_snapshot.scanner import (
    ProjectSnapshotScanError,
    resolve_repo_root,
)


class NarrowEvidenceError(RuntimeError):
    """The current checkout cannot produce trustworthy boundary evidence."""


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise NarrowEvidenceError("git is required for claim narrowing") from exc
    if completed.returncode != 0:
        raise NarrowEvidenceError(
            f"git {' '.join(args)} failed in {root}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout


def _target_head(root: Path, integration_target: str) -> str:
    for ref in (
        f"refs/remotes/origin/{integration_target}",
        f"refs/heads/{integration_target}",
    ):
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
    raise NarrowEvidenceError(
        f"cannot resolve integration target {integration_target!r} in {root}"
    )


def _committed_changes(
    root: Path,
    *,
    base_sha: str,
    head_sha: str,
) -> tuple[list[str], list[tuple[str, str]]]:
    raw = _git(
        root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        f"{base_sha}..{head_sha}",
    )
    parts = raw.split("\x00")
    touched: list[str] = []
    renames: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if not token:
            index += 1
            continue
        operation = token[0]
        if operation == "R":
            old_path = parts[index + 1] if index + 1 < len(parts) else ""
            new_path = parts[index + 2] if index + 2 < len(parts) else ""
            if new_path:
                touched.append(new_path)
            if old_path and new_path:
                renames.append((old_path, new_path))
            index += 3
        elif operation in ("A", "M", "D", "T"):
            path = parts[index + 1] if index + 1 < len(parts) else ""
            if path:
                touched.append(path)
            index += 2
        else:
            index += 1
    return list(dict.fromkeys(touched)), renames


def _dirty_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for line in _git(
        root, "status", "--porcelain", "--untracked-files=all"
    ).splitlines():
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        if path:
            paths.append(path)
    return list(dict.fromkeys(paths))


def _without_ignored(root: Path, paths: list[str]) -> list[str]:
    if not paths:
        return []
    completed = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--no-index", "--stdin"],
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise NarrowEvidenceError(
            f"git check-ignore failed in {root}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    ignored = set(completed.stdout.splitlines())
    return [path for path in paths if path not in ignored]


def collect_narrow_boundary_evidence(
    *,
    repo_root: str | None,
    integration_target: str,
) -> dict[str, Any]:
    """Return lane-head evidence suitable for a hosted function call."""
    try:
        root = resolve_repo_root(repo_root)
    except ProjectSnapshotScanError as exc:
        raise NarrowEvidenceError(str(exc)) from exc
    head_sha = _git(root, "rev-parse", "HEAD").strip()
    target_head = _target_head(root, integration_target)
    base_sha = _git(root, "merge-base", target_head, head_sha).strip()
    touched_paths, rename_pairs = _committed_changes(
        root,
        base_sha=base_sha,
        head_sha=head_sha,
    )
    return {
        "repo_root": str(root),
        "head_sha": head_sha,
        "integration_target": integration_target,
        "touched_paths": _without_ignored(root, touched_paths),
        "uncommitted_paths": _dirty_paths(root),
        "rename_pairs": [list(pair) for pair in rename_pairs],
    }


__all__ = [
    "NarrowEvidenceError",
    "collect_narrow_boundary_evidence",
]
