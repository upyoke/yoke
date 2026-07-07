"""Product-safe git scanner for ``yoke project snapshot sync``."""

from __future__ import annotations

import os
import posixpath
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from yoke_contracts.path_snapshot import (
    SYMLINK_CANONICALIZED,
    SYMLINK_DANGLING_TARGET,
    SYMLINK_EXTERNAL_TARGET,
    PathSnapshotPayload,
    PathSnapshotSyncPayload,
    SnapshotSymlinkFact,
    all_paths_with_kinds,
    file_entry_from_source,
)


class ProjectSnapshotScanError(RuntimeError):
    """The local checkout could not produce a committed-tree payload."""


def build_sync_payload(
    repo_root: str | Path | None,
    *,
    project_id: Optional[str],
    integration_target: Optional[str],
    head_only: bool = False,
    hook_mode: bool = False,
) -> PathSnapshotSyncPayload:
    root = resolve_repo_root(repo_root)
    head = scan_ref(root, "HEAD", label="HEAD")
    snapshots = [head]
    if not head_only:
        target = integration_target or _default_integration_target(root)
        resolved = _resolve_integration_ref(root, target)
        if resolved is not None:
            ref, sha = resolved
            if sha == head.commit_sha:
                snapshots.append(head.model_copy(update={"ref": target}))
            else:
                snapshots.append(
                    scan_ref(root, ref, label=target, expected_sha=sha)
                )
        else:
            head.warnings.append(
                f"integration target {target!r} was not found; synced HEAD only"
            )
    return PathSnapshotSyncPayload(
        project_id=project_id,
        repo_root=str(root),
        snapshots=snapshots,
        hook_mode=hook_mode,
    )


def resolve_repo_root(repo_root: str | Path | None) -> Path:
    candidate = Path(repo_root).expanduser() if repo_root else Path.cwd()
    proc = _git(candidate, "rev-parse", "--show-toplevel")
    root = Path(proc.stdout.strip())
    if not root:
        raise ProjectSnapshotScanError(
            f"{candidate} is not inside a git checkout"
        )
    return root


def scan_ref(
    repo_root: str | Path,
    ref: str,
    *,
    label: Optional[str] = None,
    expected_sha: Optional[str] = None,
) -> PathSnapshotPayload:
    root = Path(repo_root)
    commit_sha = expected_sha or _rev_parse(root, ref)
    entries = _ls_tree(root, ref)
    file_paths = [path for _mode, kind, _sha, path in entries if kind == "blob"]
    sources = _blob_sources(
        root, [(sha, path) for _mode, kind, sha, path in entries if kind == "blob"]
    )
    symlinks = _symlink_facts(entries, sources)
    payload = PathSnapshotPayload(
        ref=label or ref,
        commit_sha=commit_sha,
        files=[file_entry_from_source(path, sources.get(path, "")) for path in file_paths],
        symlinks=symlinks,
        warnings=_dirty_warnings(root),
    )
    # Exercise shared path derivation during scanning so invalid payloads fail
    # client-side before a network call.
    all_paths_with_kinds([entry.path for entry in payload.files])
    return payload


def _git(repo_root: Path, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=not binary,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProjectSnapshotScanError("git is required for snapshot sync") from exc
    if proc.returncode != 0:
        detail = (
            proc.stderr if isinstance(proc.stderr, str)
            else proc.stderr.decode("utf-8", errors="replace")
        ).strip()
        raise ProjectSnapshotScanError(
            f"git {' '.join(args)} failed in {repo_root}: {detail}"
        )
    return proc


def _rev_parse(repo_root: Path, ref: str) -> str:
    sha = _git(repo_root, "rev-parse", "--verify", ref).stdout.strip()
    if not sha:
        raise ProjectSnapshotScanError(f"ref {ref!r} resolved to an empty SHA")
    return sha


def _ls_tree(repo_root: Path, ref: str) -> List[Tuple[str, str, str, str]]:
    proc = _git(repo_root, "ls-tree", "-r", "-z", "--full-tree", ref, binary=True)
    rows: List[Tuple[str, str, str, str]] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        meta, path_raw = raw.split(b"\t", 1)
        mode, kind, sha = meta.decode("ascii").split(" ", 2)
        path = path_raw.decode("utf-8", errors="surrogateescape")
        rows.append((mode, kind, sha, path))
    return rows


def _blob_sources(
    repo_root: Path,
    blobs: Sequence[Tuple[str, str]],
) -> Dict[str, str]:
    sources: Dict[str, str] = {}
    if not blobs:
        return sources
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(repo_root), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ProjectSnapshotScanError("git is required for snapshot sync") from exc
    request = "".join(f"{sha}\n" for sha, _path in blobs).encode("ascii")
    stdout, stderr = proc.communicate(request)
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise ProjectSnapshotScanError(
            f"git cat-file --batch failed in {repo_root}: {detail}"
        )
    offset = 0
    for expected_sha, path in blobs:
        try:
            line_end = stdout.index(b"\n", offset)
        except ValueError as exc:
            raise ProjectSnapshotScanError(
                f"git cat-file ended before blob header for {path}"
            ) from exc
        header = stdout[offset:line_end].decode("ascii", errors="replace")
        parts = header.split()
        if len(parts) != 3 or parts[0] != expected_sha or parts[1] != "blob":
            raise ProjectSnapshotScanError(
                f"git cat-file returned unexpected header for {path}: {header}"
            )
        size = int(parts[2])
        start = line_end + 1
        end = start + size
        data = stdout[start:end]
        try:
            sources[path] = data.decode("utf-8")
        except UnicodeDecodeError:
            sources[path] = ""
        offset = end + 1
    return sources


def _symlink_facts(
    entries: Sequence[Tuple[str, str, str, str]],
    sources: Dict[str, str],
) -> List[SnapshotSymlinkFact]:
    observed_paths = {
        path for _mode, kind, _sha, path in entries if kind == "blob"
    }
    observed_paths.update(path for path, _kind in all_paths_with_kinds(observed_paths))
    facts: List[SnapshotSymlinkFact] = []
    for mode, kind, _sha, path in entries:
        if kind != "blob" or mode != "120000":
            continue
        target_attempt = sources.get(path, "").strip()
        canonical = _canonical_symlink_path(path, target_attempt)
        if canonical is None:
            facts.append(SnapshotSymlinkFact(
                path=path,
                reason=SYMLINK_EXTERNAL_TARGET,
                target_attempt=target_attempt,
            ))
        elif canonical in observed_paths:
            facts.append(SnapshotSymlinkFact(
                path=path,
                reason=SYMLINK_CANONICALIZED,
                target_attempt=target_attempt,
                canonical_path=canonical,
            ))
        else:
            facts.append(SnapshotSymlinkFact(
                path=path,
                reason=SYMLINK_DANGLING_TARGET,
                target_attempt=target_attempt,
            ))
    return facts


def _canonical_symlink_path(path: str, target: str) -> Optional[str]:
    if not target or target.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    if joined in ("", ".") or joined.startswith("../") or joined == "..":
        return None
    return joined


def _dirty_warnings(repo_root: Path) -> List[str]:
    status = _git(repo_root, "status", "--porcelain").stdout.splitlines()
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


def _default_integration_target(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "symbolic-ref", "--quiet", "--short",
         "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        text = proc.stdout.strip()
        if text.startswith("origin/"):
            return text.split("/", 1)[1]
    return os.environ.get("YOKE_INTEGRATION_TARGET", "main")


def _resolve_integration_ref(
    repo_root: Path, integration_target: str
) -> Optional[Tuple[str, str]]:
    origin_ref = f"refs/remotes/origin/{integration_target}"
    local_ref = f"refs/heads/{integration_target}"
    origin_sha = _try_rev_parse(repo_root, origin_ref)
    local_sha = _try_rev_parse(repo_root, local_ref)
    if origin_sha and local_sha and origin_sha != local_sha:
        if not (
            _is_ancestor(repo_root, origin_sha, local_sha)
            or _is_ancestor(repo_root, local_sha, origin_sha)
        ):
            raise ProjectSnapshotScanError(
                f"origin/{integration_target} and refs/heads/{integration_target} "
                "have diverged; reconcile before snapshot sync"
            )
    if origin_sha:
        return origin_ref, origin_sha
    if local_sha:
        return local_ref, local_sha
    return None


def _try_rev_parse(repo_root: Path, ref: str) -> Optional[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor",
         ancestor, descendant],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


__all__ = [
    "ProjectSnapshotScanError",
    "build_sync_payload",
    "resolve_repo_root",
    "scan_ref",
]
