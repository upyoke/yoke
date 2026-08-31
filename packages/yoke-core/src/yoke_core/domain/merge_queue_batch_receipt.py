"""Batch verification receipts for queue-landed merges.

A merge-group run validates one combined head for a whole train, so each
member item records that shared proof alongside its own landing: a
covering-eligible ``ci_run`` QA row whose ``raw_result`` carries
``verification_tree.head_sha`` — the same key the identical-tree
covering-evidence readers already compare by tree object id — plus a
``merge_queue_batch`` block naming the members, the combined head, and
the merge_group run URL so per-item evidence stays auditable.

This extends the existing covering-evidence contract rather than minting
a parallel record type: readers that skip re-verification for a tree a
passing run already covered accept these rows unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.engines.merge_worktree_pr_queue import (
    read_train_run,
    resolve_auth_detail,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass(frozen=True)
class BatchReceipt:
    """One train's shared verification identity, seen from one member."""

    pr_num: str
    merge_sha: str = ""
    members: tuple[str, ...] = ()
    head_sha: str = ""
    run_url: str = ""
    # What the pre-landing ruleset comparison concluded, or why it could
    # not run. A train landed without that comparison is still a train the
    # evidence must be able to name.
    drift_check: Mapping[str, str] = field(default_factory=dict)


def observe_batch(
    ctx: MergeContext,
    *,
    pr_num: str,
    member_snapshot: tuple[str, ...] = (),
    drift_check: Optional[Mapping[str, str]] = None,
) -> tuple[Optional[BatchReceipt], Optional[str]]:
    """Resolve the merge_group run and merge identity covering ``pr_num``.

    ``member_snapshot`` is the queue membership observed at entry time
    (item refs by head branch); it rides into the receipt so the batch
    stays attributable even when no run is identified. Returns
    ``(receipt, warning)`` — a receipt with an empty ``head_sha`` plus a
    warning when the run could not be identified; observation never blocks
    a landed merge. An empty combined head is the honest reading there: the
    only run this receipt may name is the one carrying the pull request's own
    queue ref marker.
    """
    auth, auth_err = resolve_auth_detail(ctx, PR_READ)
    if auth_err or auth is None:
        return None, auth_err
    owner, repo = split_repo(auth.repo)

    merge_sha = ""
    try:
        pr_response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/pulls/{pr_num}",
            ),
            token=auth.token,
        )
        pr_body = (
            pr_response.body if isinstance(pr_response.body, dict) else {}
        )
        merge_sha = str(pr_body.get("merge_commit_sha") or "")
    except RestTransportError as exc:
        return None, f"pull request read failed: {exc}"

    run, run_note = read_train_run(ctx, pr_num)
    return (
        BatchReceipt(
            pr_num=pr_num,
            merge_sha=merge_sha,
            members=member_snapshot,
            head_sha=run.head_sha if run is not None else "",
            run_url=run.url if run is not None else "",
            drift_check=dict(drift_check or {}),
        ),
        run_note,
    )


def record_batch_evidence(
    item_id: int,
    receipt: BatchReceipt,
    *,
    scope: str = "full",
    workflow: str = "",
    dispatch: Callable[..., Any] = call_dispatcher,
) -> Optional[str]:
    """Record the member's covering ``ci_run`` row; returns error text."""
    raw_result = dumps_compact({
        "verification_tree": {"head_sha": receipt.head_sha},
        "merge_queue_batch": {
            "members": list(receipt.members),
            "combined_head_sha": receipt.head_sha,
            "run_url": receipt.run_url,
            "pr_num": receipt.pr_num,
            "merge_sha": receipt.merge_sha,
            "drift_check": dict(receipt.drift_check),
        },
    })
    response = dispatch(
        function_id="merge.tests.record_post_rebase_ci_run",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={
            "scope": scope,
            "workflow": workflow,
            "verdict": "pass",
            "raw_result": raw_result,
            "performed_by": "ci_run",
        },
    )
    if getattr(response, "success", False):
        return None
    error = getattr(response, "error", None)
    return (
        getattr(error, "message", None)
        or "batch evidence recording failed"
    )


__all__ = ["BatchReceipt", "observe_batch", "record_batch_evidence"]
