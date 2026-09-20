"""Persist a lane's current HEAD as the candidate the control plane records.

``item_worktrees.commit_sha`` is what every later question about "which
commit is this lane offering" reads -- the merge boundary's accepted-sha
comparison above all. The git post-commit hook keeps it current for work
that arrives as commits, which is almost all of it.

Almost. A rebase advances HEAD without committing anything, so the hook
never fires and the row silently keeps a commit the lane has moved off. The
gate then records its CI run against the new head while the merge boundary
still compares the old one, and the two never meet again: the merge refuses
with a stale candidate, and the retry rebases once more. Whatever moves a
lane's HEAD without a commit therefore records it here.

The write goes through the registered ``project.snapshot.sync`` surface the
post-commit hook itself drives, rather than touching the row directly. That
is what keeps it correct on a relayed https project, where there is no local
database to write to and the server performs the same
``record_head_for_checkout`` call. ``head_only`` asks for the hook's fast
identity-only shape -- HEAD's commit, no full tree content scan.

Recording is always best-effort, for the same reason the hook's is: it runs
after the work it describes has already happened, so a failure here has
nothing to unwind and must never be turned into one. It is reported rather
than swallowed, because a lane whose head went unrecorded is exactly the
state that is invisible until a merge refuses days later.

Best-effort is not the same as hurried. The snapshot surface defaults its
relay deadline to the git post-commit hook's, which is short so a hook can
never leave a developer waiting on ``git commit``. Nothing waits on a
recording taken after a publish or a rebase, so that budget buys nothing
here and costs the whole write: the deadline expired mid-response and left
the row holding a commit the lane had moved off. Every caller in this module
therefore asks for the relay's ordinary deadline instead.
"""

from __future__ import annotations

import shlex
import sys
from typing import TextIO
from yoke_core.domain.project_attribution import UnattributedProjectError, required_project


def rerecord_command(project: str, checkout_path: str) -> str:
    """The command that records ``checkout_path``'s HEAD on its own.

    ``--head-only`` asks the snapshot surface for HEAD's identity and
    nothing else, so it moves the candidate without anything being
    committed. That is what makes it the recovery a lane whose work is
    finished can actually perform -- unlike waiting for a next commit,
    which such a lane has no reason to make.
    """
    return shlex.join(
        [
            "yoke", "project", "snapshot", "sync", str(checkout_path),
            "--project", str(project), "--head-only",
        ]
    )


def record_lane_head(project: str, checkout_path: str) -> str:
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
    from yoke_cli.commands.adapters.project_snapshot import (
        sync_local_snapshot_for_write,
    )

    try:
        resolved = required_project(
            project,
            operation="recording this lane's head",
            checkout=checkout_path,
        )
    except UnattributedProjectError as exc:
        return str(exc)

    rerecord = rerecord_command(resolved, str(checkout_path))
    result = sync_local_snapshot_for_write(
        project=resolved,
        repo_root=str(checkout_path),
        integration_target=None,
        session_id=None,
        head_only=True,
        # The hook's deadline is the surface default; this is not a hook.
        timeout_s=None,
        retry_command=rerecord,
    )
    # ``deferred`` is a recording the surface accepted and will complete;
    # it is not a failure to report.
    if result.get("status") in ("ok", "deferred"):
        return ""
    detail = str(
        result.get("message") or result.get("status") or "snapshot sync failed"
    )
    # The surface withholds a repair where retrying cannot be the answer --
    # an authorization refusal answers the same way however often it is
    # asked. Naming the re-record anyway is still honest there: it is what
    # takes the stamp once the named reason is dealt with.
    repair = str(result.get("repair_command") or "") or rerecord
    return f"{detail}; record it with `{repair}`, which needs no commit"


def record_published_lane_head(
    project: str,
    checkout_path: str,
    *,
    source_ref: str = "HEAD",
    stream: TextIO | None = None,
) -> None:
    """Record a just-published lane's HEAD, naming a failure but never raising.

    Publishing is the point the head becomes the lane's shared identity, so
    it is the honest moment to record it: before the push the commit is
    local and provisional, and after it every reader expects the control
    plane to name the same candidate CI was handed.

    ``source_ref`` is what the caller published. Only ``HEAD`` is this
    checkout's own lane: a publisher naming a recorded commit instead has
    lost its lane worktree, so this checkout sits on some other tree and
    recording its HEAD would invent exactly the drift this prevents. The
    registered surface can only read HEAD, so that case records nothing.
    """
    if source_ref != "HEAD":
        return
    detail = record_lane_head(project, checkout_path)
    if detail:
        print(
            f"warning: published lane head at {checkout_path} was not "
            f"recorded as its candidate; a merge may refuse this lane as "
            f"stale until it is: {detail}",
            file=stream or sys.stderr,
        )


__all__ = ["record_lane_head", "record_published_lane_head", "rerecord_command"]
