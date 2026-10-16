"""Product-safe git scanner for ``yoke project snapshot sync``."""

from __future__ import annotations

import posixpath
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from yoke_cli.project_snapshot.scan_progress import ScanProgress
from yoke_cli.project_snapshot.scanner_blobs import BlobScanError, blob_sources
from yoke_contracts.path_snapshot import (
    SYMLINK_CANONICALIZED,
    SYMLINK_DANGLING_TARGET,
    SYMLINK_EXTERNAL_TARGET,
    PathSnapshotPayload,
    SnapshotFileEntry,
    SnapshotSymlinkFact,
    all_paths_with_kinds,
)
from yoke_contracts.path_source_scan import file_entry_from_source
from yoke_contracts import terminal_detached_process


class ProjectSnapshotScanError(RuntimeError):
    """The local checkout could not produce a committed-tree payload."""


def resolve_repo_root(repo_root: str | Path | None) -> Path:
    candidate = Path(repo_root).expanduser() if repo_root else Path.cwd()
    proc = run_git(candidate, "rev-parse", "--show-toplevel")
    root = Path(proc.stdout.strip())
    if not root:
        raise ProjectSnapshotScanError(f"{candidate} is not inside a git checkout")
    return root


def scan_ref(
    repo_root: str | Path,
    ref: str,
    *,
    label: Optional[str] = None,
    expected_sha: Optional[str] = None,
    include_contents: bool = True,
    warnings: Optional[List[str]] = None,
) -> PathSnapshotPayload:
    """Scan every file of ``ref``: the full inventory one snapshot stores."""
    root = Path(repo_root)
    commit_sha = expected_sha or rev_parse(root, ref)
    name = label or ref
    notes = dirty_warnings(root) if warnings is None else list(warnings)
    if not include_contents:
        return PathSnapshotPayload(
            ref=name,
            commit_sha=commit_sha,
            files=[],
            warnings=notes,
            contents_included=False,
        )
    entries = ls_tree(root, commit_sha)
    blobs = [(sha, path) for _mode, kind, sha, path in entries if kind == "blob"]
    files, sources = scan_blobs(root, blobs, name)
    payload = PathSnapshotPayload(
        ref=name,
        commit_sha=commit_sha,
        files=files,
        symlinks=symlink_facts(entries, sources),
        warnings=notes,
    )
    all_paths_with_kinds([entry.path for entry in payload.files])
    return payload


def scan_blobs(
    root: Path,
    blobs: Sequence[Tuple[str, str]],
    name: str,
) -> Tuple[List[SnapshotFileEntry], Dict[str, str]]:
    """Read and parse ``(blob sha, path)`` pairs into file entries."""
    progress = ScanProgress()
    progress.emit(f"scanning {name}", force=True)
    progress.emit(f"reading {len(blobs)} blobs", force=True)
    try:
        sources = blob_sources(
            root,
            blobs,
            on_progress=lambda done, total: progress.emit(
                f"read {done}/{total} blobs",
                force=done >= total,
            ),
        )
    except BlobScanError as exc:
        raise ProjectSnapshotScanError(str(exc)) from exc
    files: List[SnapshotFileEntry] = []
    total = len(blobs)
    for index, (_sha, path) in enumerate(blobs, start=1):
        files.append(file_entry_from_source(path, sources.get(path, "")))
        progress.emit(f"parsed {index}/{total} files", force=index >= total)
    progress.emit(f"scanned {name} ({len(files)} files)", force=True)
    return files, sources


def run_git(
    repo_root: Path, *args: str, binary: bool = False
) -> subprocess.CompletedProcess:
    try:
        proc = terminal_detached_process.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=not binary,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProjectSnapshotScanError("git is required for snapshot sync") from exc
    if proc.returncode != 0:
        detail = (
            proc.stderr
            if isinstance(proc.stderr, str)
            else proc.stderr.decode("utf-8", errors="replace")
        ).strip()
        raise ProjectSnapshotScanError(
            f"git {' '.join(args)} failed in {repo_root}: {detail}"
        )
    return proc


def rev_parse(repo_root: Path, ref: str) -> str:
    sha = run_git(repo_root, "rev-parse", "--verify", ref).stdout.strip()
    if not sha:
        raise ProjectSnapshotScanError(f"ref {ref!r} resolved to an empty SHA")
    return sha


def ls_tree(repo_root: Path, ref: str) -> List[Tuple[str, str, str, str]]:
    proc = run_git(repo_root, "ls-tree", "-r", "-z", "--full-tree", ref, binary=True)
    rows: List[Tuple[str, str, str, str]] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        meta, path_raw = raw.split(b"\t", 1)
        mode, kind, sha = meta.decode("ascii").split(" ", 2)
        path = path_raw.decode("utf-8", errors="surrogateescape")
        rows.append((mode, kind, sha, path))
    return rows


def symlink_facts(
    entries: Sequence[Tuple[str, str, str, str]],
    sources: Dict[str, str],
) -> List[SnapshotSymlinkFact]:
    observed_paths = {path for _mode, kind, _sha, path in entries if kind == "blob"}
    observed_paths.update(path for path, _kind in all_paths_with_kinds(observed_paths))
    facts: List[SnapshotSymlinkFact] = []
    for mode, kind, _sha, path in entries:
        if kind != "blob" or mode != "120000":
            continue
        target_attempt = sources.get(path, "").strip()
        canonical = _canonical_symlink_path(path, target_attempt)
        if canonical is None:
            facts.append(
                SnapshotSymlinkFact(
                    path=path,
                    reason=SYMLINK_EXTERNAL_TARGET,
                    target_attempt=target_attempt,
                )
            )
        elif canonical in observed_paths:
            facts.append(
                SnapshotSymlinkFact(
                    path=path,
                    reason=SYMLINK_CANONICALIZED,
                    target_attempt=target_attempt,
                    canonical_path=canonical,
                )
            )
        else:
            facts.append(
                SnapshotSymlinkFact(
                    path=path,
                    reason=SYMLINK_DANGLING_TARGET,
                    target_attempt=target_attempt,
                )
            )
    return facts


def _canonical_symlink_path(path: str, target: str) -> Optional[str]:
    if not target or target.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    if joined in ("", ".") or joined.startswith("../") or joined == "..":
        return None
    return joined


def dirty_warnings(repo_root: Path) -> List[str]:
    status = run_git(repo_root, "status", "--porcelain").stdout.splitlines()
    if not status:
        return []
    staged = sum(1 for line in status if line[:1].strip())
    unstaged = sum(1 for line in status if len(line) > 1 and line[1:2].strip())
    untracked = sum(1 for line in status if line.startswith("??"))
    return [
        "working tree has uncommitted changes; snapshot sync records committed "
        f"git tree state only (staged={staged}, unstaged={unstaged}, "
        f"untracked={untracked})"
    ]


__all__ = [
    "ProjectSnapshotScanError",
    "dirty_warnings",
    "ls_tree",
    "resolve_repo_root",
    "rev_parse",
    "run_git",
    "scan_blobs",
    "scan_ref",
    "symlink_facts",
]
