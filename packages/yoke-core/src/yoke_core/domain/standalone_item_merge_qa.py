"""Pre-merge QA proof check for standalone item branches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.merge_preflight_github_lock_retry import (
    call_with_machine_lock_retry,
)
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.qa_phase_boundary import applies_at_pre_merge
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_terminal_settlement import (
    BlockingRequirementIssue,
    blocking_requirement_issues,
    requirement_issue_errors,
)
from yoke_core.domain.standalone_item_merge_lane import (
    lane_resolution_error,
    merge_source_lane,
)


_DONE_TRANSITION = "done"


def item_for_merge_phase(
    item: dict[str, Any],
    *,
    leaves_status_unchanged: bool,
) -> dict[str, Any]:
    """Return the QA view applicable to this merge lifecycle phase.

    Pre-merge admission evaluates ``verification`` rows only. Post-deployment
    acceptance stays out of the landing preflight whether or not
    ``--skip-status`` postpones terminal close-out. Requirements and attached
    plans bound to the terminal ``done`` transition are additionally deferred
    when the merge itself will not walk that close-out; unbound, review-bound,
    and unknown transition verification rows remain fail-closed.
    """

    def before_done(
        rows: list[dict[str, Any]], transition_key: str
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if str(row.get(transition_key) or "").strip() != _DONE_TRANSITION
        ]

    requirements = [
        row
        for row in list(item.get("qa_requirements") or [])
        if applies_at_pre_merge(row)
    ]
    attachments = list(item.get("qa_plan_attachments") or [])
    if leaves_status_unchanged:
        requirements = before_done(requirements, "workflow_transition_id")
        attachments = before_done(attachments, "transition_id")
    return {
        **item,
        "qa_requirements": requirements,
        "qa_plan_attachments": attachments,
    }


def _hydrate_run_identity(requirement: dict[str, Any]) -> str:
    """Read raw run proof through the deployed, backward-compatible API."""
    if requirement.get("recorded_head_sha") or requirement.get("run_id") is None:
        return ""
    requirement_id = int(requirement["id"])
    response = call_with_machine_lock_retry(
        lambda: call_dispatcher(
            function_id="qa.run.list",
            target=TargetRef(
                kind="qa_requirement",
                qa_requirement_id=requirement_id,
            ),
            payload={"requirement_id": requirement_id},
        )
    )
    if not response.success:
        detail = response.error.message if response.error else "read failed"
        return f"could not read QA runs for requirement {requirement_id}: {detail}"
    rows = list((response.result or {}).get("rows") or [])
    if not rows:
        return ""
    latest = rows[-1]
    requirement.update(
        run_id=latest.get("id"),
        verdict=latest.get("verdict"),
        execution_status=latest.get("execution_status"),
        case_outcome=latest.get("case_outcome"),
        completed_at=latest.get("completed_at"),
        recorded_head_sha=recorded_head_sha(latest.get("raw_result")),
    )
    return ""


def evaluate(
    item: dict[str, Any],
    *,
    public_ref: str,
    repo_root: Path,
    branch: str,
) -> tuple[str, list[BlockingRequirementIssue], str]:
    """Return the merging commit, blocking issues, and any hard error."""
    source_error = lane_resolution_error(item)
    if source_error:
        return "", [], source_error
    lane = merge_source_lane(item) or {}
    commit_sha = str(lane.get("commit_sha") or "").strip() or git.head_of(
        str(repo_root), branch
    )
    if not commit_sha:
        return "", [], f"cannot resolve the commit carried by branch {branch!r}"
    requirements = list(item.get("qa_requirements") or [])
    for requirement in requirements:
        hydration_error = _hydrate_run_identity(requirement)
        if hydration_error:
            return commit_sha, [], hydration_error
    attachments = list(item.get("qa_plan_attachments") or [])
    require_any = bool(requirements) or any(
        int(attachment.get("case_count") or 0) > 0 for attachment in attachments
    )
    return (
        commit_sha,
        blocking_requirement_issues(
            requirements,
            accepted_shas=(commit_sha,),
            public_ref=public_ref,
            require_any=require_any,
        ),
        "",
    )


def preflight(
    item: dict[str, Any],
    *,
    public_ref: str,
    repo_root: Path,
    branch: str,
) -> tuple[str, str]:
    """Return the merging commit and any terminal-QA refusal before landing."""
    commit_sha, issues, error = evaluate(
        item,
        public_ref=public_ref,
        repo_root=repo_root,
        branch=branch,
    )
    if error:
        return commit_sha, error
    errors = requirement_issue_errors(
        issues,
        public_ref=public_ref,
        target_status="done",
    )
    if errors:
        return commit_sha, (
            "merge refused before the branch landed:\n" + "\n".join(errors)
        )
    plan_refusal = _item_qa_plan_refusal(item, public_ref=public_ref)
    if plan_refusal:
        return commit_sha, plan_refusal
    return commit_sha, ""


def _item_qa_plan_refusal(item: dict[str, Any], *, public_ref: str) -> str:
    """Refuse a landing whose flow will later ask this item to prove itself."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_item_stage_plan_gate import (
        missing_item_qa_plan_refusal,
    )

    project = item.get("project")
    project_slug = (
        str(project.get("slug") or "") if isinstance(project, dict) else str(project or "")
    )
    item_id = item.get("id")
    if item_id is None or not project_slug:
        return ""
    conn = connect()
    try:
        return missing_item_qa_plan_refusal(
            conn,
            item_id=int(item_id),
            public_ref=public_ref,
            project=project_slug,
            flow_id=str(item.get("deployment_flow") or ""),
        )
    finally:
        conn.close()


__all__ = ["evaluate", "item_for_merge_phase", "preflight"]
