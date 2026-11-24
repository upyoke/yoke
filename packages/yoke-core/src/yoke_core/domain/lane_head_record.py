"""Read a local lane's Git HEAD and record its candidate through snapshot sync.

Commands reconcile the selected checkout before they consume its candidate.
The registered snapshot write also works when the project uses an HTTPS relay.
Operations that have already moved or published HEAD report recording failures
as warnings because the Git operation itself has already succeeded.
"""

from __future__ import annotations

from yoke_contracts.runtime_ports.project_snapshot import get_project_snapshot

import re
import subprocess
import sys
from pathlib import Path
from collections.abc import Mapping
from typing import TextIO

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.project_attribution import (
    UnattributedProjectError,
    required_project,
)


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def local_lane_head(lane: Mapping[str, object]) -> tuple[str, str]:
    """Return the selected checkout's stable HEAD, or a named refusal."""
    path = str(lane.get("path") or lane.get("worktree_path") or "").strip()
    if not path:
        return "", ""
    checkout = Path(path)
    try:
        checkout.stat()
    except FileNotFoundError:
        return "", ""
    except OSError:
        return "", _unreadable(checkout)
    try:
        if Path(_git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout.resolve():
            return "", _unreadable(checkout)
        for marker, operation in (
            ("rebase-merge", "rebase"),
            ("rebase-apply", "rebase"),
            ("MERGE_HEAD", "merge"),
        ):
            git_path = _git(checkout, "rev-parse", "--git-path", marker)
            if (checkout / git_path).exists():
                return "", compose_refusal(
                    f"lane_head_{operation}_in_progress: {checkout}",
                    recovery=f"finish or abort the Git {operation}, then rerun the same command",
                )
        head = _git(checkout, "rev-parse", "--verify", "HEAD^{commit}")
        branch = _git(checkout, "rev-parse", "--abbrev-ref", "HEAD")
    except (OSError, subprocess.SubprocessError):
        return "", _unreadable(checkout)
    expected = str(lane.get("branch") or "").strip()
    if expected and branch != expected:
        return "", compose_refusal(
            f"lane_head_branch_mismatch: {checkout} is on {branch!r}, expected {expected!r}",
            recovery=f"restore the recorded branch {expected!r}, then rerun the same command",
        )
    return head, ""


def _unreadable(checkout: Path) -> str:
    return compose_refusal(
        f"lane_head_unreadable: could not read Git HEAD at {checkout}",
        recovery="repair the Git checkout, then rerun the same command",
    )


def reconcile_lane_head(
    project: str, lane: Mapping[str, object], *, session_id: str | None = None
) -> tuple[str, str]:
    """Return a newly recorded HEAD and any refusal. Empty HEAD means no write."""
    head, error = local_lane_head(lane)
    if error or not head or head == str(lane.get("commit_sha") or "").strip():
        return "", error
    checkout = str(lane.get("path") or lane.get("worktree_path"))
    try:
        detail = record_lane_head(project, checkout, expected_head=head, session_id=session_id)
    except Exception as exc:
        detail = str(exc) or type(exc).__name__
    if detail:
        return "", compose_refusal(
            f"lane_head_unrecorded: {detail}", recovery="rerun the same command"
        )
    return head, ""


def record_lane_head(
    project: str, checkout_path: str, *, expected_head: str = "", session_id: str | None = None
) -> str:
    """Record ``checkout_path``'s HEAD as its lane candidate.

    Returns why the recording did not happen and what records it after all,
    or ``""`` when it did. The two travel together because every reader of
    this string prints it to whoever is standing in the lane, and a named
    gap they cannot close is the failure mode this exists to prevent. An
    unnamed project is one such reason rather than a default: recording
    another project's lane against this installation's own is a row that
    reads exactly like a deliberate write and is wrong in a way no later
    reader can detect.
    """
    sync_local_snapshot_for_write = get_project_snapshot().sync_local_snapshot_for_write

    try:
        resolved = required_project(
            project,
            operation="recording this lane's head",
            checkout=checkout_path,
        )
    except UnattributedProjectError as exc:
        return str(exc)

    result = sync_local_snapshot_for_write(
        project=resolved,
        repo_root=str(checkout_path),
        integration_target=None,
        session_id=session_id,
        head_only=True,
        # The hook's deadline is the surface default; this is not a hook.
        timeout_s=None,
    )
    status = result.get("status")
    if status == "ok":
        if expected_head and not any(
            row.get("ref") == "HEAD"
            and row.get("commit_sha") == expected_head
            and row.get("lane_head_recorded")
            for row in result.get("snapshots") or ()
        ):
            return f"snapshot did not confirm lane HEAD {expected_head}"
        return ""
    if status == "deferred" and not expected_head:
        return ""
    detail = str(result.get("message") or status or "snapshot sync failed")
    repair = result.get("repair_command")
    return f"{detail}. Recovery: run `{repair}`" if repair else detail


def _published_checkout_matches(
    checkout_path: str,
    selected_checkout: str | None,
    branch: str | None,
    source_ref: str,
    stream: TextIO | None,
) -> bool:
    """A full SHA is stampable only as the selected clean live lane's HEAD."""
    if not selected_checkout or not branch:
        return False
    checkout = Path(checkout_path).resolve()
    if not checkout.is_dir() or Path(selected_checkout).resolve() != checkout:
        return False
    try:
        matches = (
            re.fullmatch(r"[0-9a-f]{40}", source_ref) is not None
            and _git(checkout, "symbolic-ref", "--quiet", "--short", "HEAD") == branch
            and _git(checkout, "rev-parse", "HEAD") == source_ref
            and not _git(checkout, "status", "--porcelain", "--untracked-files=normal")
        )
    except (OSError, subprocess.SubprocessError):
        matches = False
    if not matches:
        print(
            "warning: qa_published_head_unproven: selected checkout is not the "
            f"clean published {branch}@{source_ref}; no candidate was stamped. "
            "Restore that exact live lane identity under its matching claim, "
            "then rerun the same command.",
            file=stream or sys.stderr,
        )
    return matches


def record_published_lane_head(
    project: str,
    checkout_path: str,
    *,
    source_ref: str = "HEAD",
    selected_checkout: str | None = None,
    branch: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Record a just-published lane's HEAD, naming a failure but never raising.

    Publishing is the point the head becomes the lane's shared identity, so
    it is the honest moment to record it: before the push the commit is
    local and provisional, and after it every reader expects the control
    plane to name the same candidate CI was handed.

    A full SHA does not establish a live checkout. First prove the selected
    checkout, branch and clean HEAD equal that SHA; only then use the existing
    HEAD recorder. Missing/cleaned lanes and other checkouts record nothing.
    The registered surface retains all claim and ownership checks.
    """
    if source_ref != "HEAD" and _published_checkout_matches(
        checkout_path,
        selected_checkout,
        branch,
        source_ref,
        stream,
    ):
        source_ref = "HEAD"
    if source_ref != "HEAD":
        return
    detail = record_lane_head(project, checkout_path)
    if detail:
        print(
            f"warning: published lane head at {checkout_path} was not "
            f"recorded as its candidate; a merge may refuse this lane as "
            f"stale until it is: {detail}. Resolve the reported cause, then "
            "rerun the same command.",
            file=stream or sys.stderr,
        )


__all__ = ["local_lane_head", "reconcile_lane_head", "record_lane_head", "record_published_lane_head"]
