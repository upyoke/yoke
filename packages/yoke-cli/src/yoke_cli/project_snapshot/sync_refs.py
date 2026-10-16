"""Which commits one ``yoke project snapshot sync`` records.

A sync records this checkout's HEAD plus, unless asked for HEAD only, the
integration target it lands on. Resolving those refs is cheap git plumbing;
reading file contents is the scanner's job and happens per ref afterwards.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from yoke_cli.project_snapshot.scanner import (
    ProjectSnapshotScanError,
    dirty_warnings,
    resolve_repo_root,
    rev_parse,
    scan_ref,
)
from yoke_contracts.path_snapshot import PathSnapshotSyncPayload
from yoke_contracts import terminal_detached_process


@dataclass(frozen=True)
class SyncRef:
    """One commit to record: ``label`` names it to the server."""

    label: str
    commit_sha: str
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SyncPlan:
    repo_root: Path
    head: SyncRef
    integration: Optional[SyncRef] = None

    @property
    def refs(self) -> List[SyncRef]:
        return [self.head] + ([self.integration] if self.integration else [])


def plan_sync(
    repo_root: str | Path | None,
    *,
    integration_target: Optional[str],
    head_only: bool = False,
) -> SyncPlan:
    root = resolve_repo_root(repo_root)
    notes = dirty_warnings(root)
    head_sha = rev_parse(root, "HEAD")
    if head_only:
        return SyncPlan(root, SyncRef("HEAD", head_sha, notes))
    target = integration_target or _default_integration_target(root)
    resolved = _resolve_integration_ref(root, target)
    if resolved is None:
        missing = f"integration target {target!r} was not found; synced HEAD only"
        return SyncPlan(root, SyncRef("HEAD", head_sha, [*notes, missing]))
    _ref, target_sha = resolved
    return SyncPlan(
        root,
        SyncRef("HEAD", head_sha, notes),
        SyncRef(target, target_sha, notes),
    )


def identity_sync_payload(
    plan: SyncPlan,
    *,
    project_id: Optional[str],
    hook_mode: bool,
) -> PathSnapshotSyncPayload:
    """The payload that records commit identities and stores no snapshot."""
    return PathSnapshotSyncPayload(
        project_id=project_id,
        repo_root=str(plan.repo_root),
        snapshots=[
            scan_ref(
                plan.repo_root,
                ref.commit_sha,
                label=ref.label,
                expected_sha=ref.commit_sha,
                include_contents=False,
                warnings=ref.warnings,
            )
            for ref in plan.refs
        ],
        hook_mode=hook_mode,
    )


def _default_integration_target(repo_root: Path) -> str:
    proc = terminal_detached_process.run(
        [
            "git",
            "-C",
            str(repo_root),
            "symbolic-ref",
            "--quiet",
            "--short",
            "refs/remotes/origin/HEAD",
        ],
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
    proc = terminal_detached_process.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    proc = terminal_detached_process.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


__all__ = [
    "SyncPlan",
    "SyncRef",
    "identity_sync_payload",
    "plan_sync",
]
