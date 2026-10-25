"""Prove standalone lane QA before selecting its landing route."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_core.domain import merge_queue_landing_timeout as _timeout
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


def proof_check(
    item: dict[str, Any],
    args: argparse.Namespace,
    *,
    public_ref: str,
    repo_root: Path,
    branch: str,
) -> tuple[str, str]:
    """Read-only QA proof answer. Returns ``(blocker, merge_will_note)``.

    Passing evidence from the lane history needs no new run.
    """
    qa_item = item_for_merge_phase(item, leaves_status_unchanged=bool(args.skip_status))
    _sha, qa_error = qa_preflight(
        qa_item, public_ref=public_ref, repo_root=repo_root, branch=branch
    )
    return qa_error, ""


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
    enter_review: Callable[[], str],
) -> tuple[Optional[Any], str]:
    """Prove the lane before landing it. Returns ``(outcome, refusal)``.

    ``enter_review`` moves the item into its review stage once the proof
    holds and before anything lands; it returns a refusal or empty.
    """
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
        return None, qa_error
    review_refusal = enter_review()
    if review_refusal:
        return None, review_refusal
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
        retry_flake=str(getattr(args, "retry_flake", "")),
    ), ""


__all__ = ["proof_check", "verify_and_land"]
