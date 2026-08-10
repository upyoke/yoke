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
    dispatch: Callable[..., Any] = call_dispatcher,
) -> StandaloneMergeOutcome:
    """Select the merge boundary for one standalone item branch.

    A project declaring the merge-queue capability lands through the
    queue; every other project keeps the standalone engine unchanged. A
    failing capability probe refuses rather than silently choosing the
    local engine for a project that may have declared the queue.
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
        )
    outcome = land_item_through_merge_queue(
        MergeContext(
            args=MergeArgs(branch=branch, target=target), project=project
        ),
        item_id=item_id,
        item_ref=item_ref or branch,
        commit_sha=commit_sha,
        target=target,
        dispatch=dispatch,
    )
    return StandaloneMergeOutcome(
        ok=outcome.ok,
        exit_code=outcome.exit_code,
        already_merged=False,
        # The lane head is what the item's own verification covered and what
        # its evidence record is answerable for; the queue's merge commit
        # belongs to the base branch, exactly as in the local engine's result.
        commit_sha=outcome.commit_sha,
        merge_sha=outcome.merge_sha,
        pushed=outcome.ok,
        error=outcome.error,
        warnings=outcome.warnings,
    )


__all__ = ["project_declares_merge_queue", "route_standalone_landing"]
