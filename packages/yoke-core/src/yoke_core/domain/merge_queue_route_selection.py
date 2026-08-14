"""Boundary selection between the merge queue and the standalone engine.

One capability probe decides where a standalone item branch lands. The
probe rides the registered raw-read surface so it relays over an https
control plane exactly as it dispatches in-process locally — the merge
boundary runs on the machine that holds the git repository, never with
its own database connection. Callers get one result shape either way:
the queue outcome is adapted into :class:`StandaloneMergeOutcome`, so
the dispatch sites that already consume the standalone engine swap a
function name and keep their handling unchanged.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.merge_queue_route import land_item_through_merge_queue
from yoke_core.domain.projects_seed_ci_workflow import (
    MERGE_QUEUE_CAPABILITY_TYPE,
)
from yoke_core.domain.standalone_item_merge import (
    StandaloneMergeOutcome,
    merge_standalone_branch,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


_PROBE_SAFE_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


def project_declares_merge_queue(
    project: str,
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> tuple[bool, Optional[str]]:
    """Read whether ``project`` declares the merge-queue capability.

    Returns ``(declared, error)``; a probe error is returned rather than
    swallowed so a declared-queue project cannot silently fall back to a
    local merge on an outage.
    """
    slug = str(project or "").strip()
    if not _PROBE_SAFE_SLUG.fullmatch(slug):
        return False, None
    response = dispatch(
        function_id=DB_READ_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={"sql": (
            "SELECT COUNT(*) FROM project_capabilities pc "
            "JOIN projects p ON p.id = pc.project_id "
            f"WHERE p.slug = '{slug}' "
            f"AND pc.type = '{MERGE_QUEUE_CAPABILITY_TYPE}'"
        )},
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        return False, (
            getattr(error, "message", None) or "capability probe failed"
        )
    rows = ((getattr(response, "result", None) or {}).get("rows")) or []
    first = rows[0] if rows else None
    value: Any = None
    if isinstance(first, dict):
        value = next(iter(first.values()), None)
    elif isinstance(first, (list, tuple)) and first:
        value = first[0]
    try:
        return int(value or 0) > 0, None
    except (TypeError, ValueError):
        return False, "capability probe returned unparseable rows"


def queue_lane_head(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    commit_sha: str,
) -> tuple[str, str]:
    """The commit a queue landing is answerable for; the reason it has none.

    The local engine derives this for itself and refuses without it. The queue
    route needs the same answer *before* it reaches a pull request, because
    the lane head is what declines convergence on a pull request that merged
    an older head, and what the landing's receipt names as the commit that
    landed. Handing the queue an empty one disables that guard and records a
    receipt naming no commit at all.

    Strongest answer first: a head the control plane recorded, then the branch
    tip the local engine falls back to, then the receipt — the only surviving
    record of what that lane carried after terminal close-out removes it, and
    what lets a re-entered landing converge.
    """
    if commit_sha:
        return commit_sha, ""
    head = git.head_of(repo_root, branch)
    if head:
        return head, ""
    recorded = receipts.load(item_id, branch, target, project=project)
    if recorded is not None and recorded.commit_sha:
        return recorded.commit_sha, ""
    return "", (
        f"queue landing for branch '{branch}' has no lane head: the control "
        f"plane recorded none, '{branch}' does not resolve in {repo_root}, "
        f"and no merge receipt records it landing on '{target}'"
    )


def route_standalone_landing(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    commit_sha: str = "",
    item_ref: str = "",
    local_merge: bool = True,
    resume_command: str = "",
    dispatch: Callable[..., Any] = call_dispatcher,
) -> StandaloneMergeOutcome:
    """Select the merge boundary for one standalone item branch.

    A project declaring the merge-queue capability lands through the
    queue; every other project keeps the standalone engine unchanged. A
    failing capability probe refuses rather than silently choosing the
    local engine for a project that may have declared the queue.

    ``resume_command`` is what the caller ran, quoted back verbatim when a
    queue landing runs out of poll budget. Only the caller knows it, and a
    resumable outcome that prints a command the operator can paste is the
    difference between resuming and reconstructing.
    """
    declared, probe_error = project_declares_merge_queue(
        project, dispatch=dispatch
    )
    if probe_error:
        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            error=f"merge-queue capability probe failed: {probe_error}",
        )
    if not declared:
        return merge_standalone_branch(
            item_id=item_id,
            branch=branch,
            commit_sha=commit_sha,
            target=target,
            repo_root=repo_root,
            project=project,
            local_merge=local_merge,
            resume_command=resume_command,
        )
    lane_head, head_error = queue_lane_head(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=repo_root,
        project=project,
        commit_sha=commit_sha,
    )
    if head_error:
        return StandaloneMergeOutcome(
            ok=False, exit_code=1, already_merged=False, error=head_error,
        )
    outcome = land_item_through_merge_queue(
        # The repository root rides along because the landing has a lane to
        # retire on this machine once the queue merges it on GitHub.
        MergeContext(
            args=MergeArgs(branch=branch, target=target),
            repo_root=repo_root,
            project=project,
        ),
        item_id=item_id,
        item_ref=item_ref or branch,
        commit_sha=lane_head,
        target=target,
        resume_command=resume_command,
        dispatch=dispatch,
    )
    return StandaloneMergeOutcome(
        ok=outcome.ok,
        exit_code=outcome.exit_code,
        already_merged=outcome.already_merged,
        # The lane head is what the item's own verification covered and what
        # its evidence record is answerable for; the queue's merge commit
        # belongs to the base branch, exactly as in the local engine's result.
        commit_sha=outcome.commit_sha,
        merge_sha=outcome.merge_sha,
        # Resolved from the landed pull request rather than from a local
        # diff, but it is the same fact the local engine reports and the
        # same fact the item's evidence record is refused without.
        touched_files=outcome.touched_files,
        pushed=outcome.ok,
        error=outcome.error,
        warnings=outcome.warnings,
    )


__all__ = [
    "project_declares_merge_queue",
    "queue_lane_head",
    "route_standalone_landing",
]
