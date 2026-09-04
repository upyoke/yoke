"""Proving a standalone lane before it is allowed to land.

The merge boundary refuses a branch whose blocking verification does not cover
the exact commit it would merge. One refusal class is recoverable rather than
terminal — a passing run bound to no commit, or to an older one — so the
proof is re-established here and re-checked before the landing route is
selected.

Kept apart from the boundary that sequences close-out because it runs only for
a lane that still has something to land: a branch the base already contains is
past the point this gate exists to hold, and re-running a SHA-bound case there
publishes a lane whose pull request may already be in the merge queue.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import merge_queue_landing_timeout as _timeout
from yoke_core.domain import standalone_item_merge_commit_bound as commit_bound
from yoke_core.domain.merge_queue_route_selection import (
    route_standalone_landing,
)
from yoke_core.domain.session_relay_launch_identity import (
    calling_session_is_relay_launched,
)
from yoke_core.domain.standalone_item_merge_qa import (
    item_for_merge_phase,
    preflight as qa_preflight,
)


def verify_and_land(
    item: dict[str, Any],
    args: argparse.Namespace,
    *,
    public_ref: str,
    item_id: int,
    branch: str,
    target: str,
    repo_root: Path,
    project: str,
) -> tuple[Optional[Any], str]:
    """Prove the lane before landing it. Returns ``(outcome, refusal)``."""
    qa_item = item_for_merge_phase(
        item,
        leaves_status_unchanged=bool(args.skip_status),
    )
    commit_sha, qa_error = qa_preflight(
        qa_item,
        public_ref=public_ref,
        repo_root=repo_root,
        branch=branch,
    )
    if qa_error:
        commit_sha, qa_error = commit_bound.recover_and_recheck(
            qa_item,
            public_ref=public_ref,
            repo_root=repo_root,
            branch=branch,
            qa_error=qa_error,
            rerecord=commit_bound.rerecord_hand_run,
            run_case=commit_bound.rerun_command_case,
        )
    if qa_error:
        return None, qa_error
    return route_standalone_landing(
        item_id=item_id,
        branch=branch,
        commit_sha=commit_sha,
        target=target,
        repo_root=str(repo_root),
        project=project,
        public_ref=public_ref,
        local_merge=not args.pr,
        resume_command=_timeout.merge_item_resume_command(public_ref, args),
        wait_for_landing=bool(getattr(args, "wait", False)),
        relay_launched=calling_session_is_relay_launched(),
    ), ""


__all__ = ["verify_and_land"]
