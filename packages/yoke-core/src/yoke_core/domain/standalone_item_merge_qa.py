"""Pre-merge QA proof check for standalone item branches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.qa_terminal_settlement import (
    blocking_requirement_issues,
    recorded_head_sha,
    requirement_issue_errors,
)


def _hydrate_run_identity(requirement: dict[str, Any]) -> str:
    """Read raw run proof through the deployed, backward-compatible API."""
    if requirement.get("recorded_head_sha") or requirement.get("run_id") is None:
        return ""
    requirement_id = int(requirement["id"])
    response = call_dispatcher(
        function_id="qa.run.list",
        target=TargetRef(
            kind="qa_requirement", qa_requirement_id=requirement_id,
        ),
        payload={"requirement_id": requirement_id},
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


def preflight(
    item: dict[str, Any], *, item_ref: str, repo_root: Path, branch: str,
) -> tuple[str, str]:
    """Return the merging commit and any terminal-QA refusal before landing."""
    commit_sha = next(
        (
            str(lane.get("commit_sha") or "").strip()
            for lane in item.get("worktrees") or []
            if str(lane.get("commit_sha") or "").strip()
        ),
        "",
    ) or git.head_of(str(repo_root), branch)
    if not commit_sha:
        return "", f"cannot resolve the commit carried by branch {branch!r}"
    requirements = [dict(row) for row in item.get("qa_requirements") or []]
    for requirement in requirements:
        hydration_error = _hydrate_run_identity(requirement)
        if hydration_error:
            return commit_sha, hydration_error
    attachments = list(item.get("qa_plan_attachments") or [])
    require_any = bool(requirements) or any(
        int(attachment.get("case_count") or 0) > 0 for attachment in attachments
    )
    issues = blocking_requirement_issues(
        requirements,
        expected_sha=commit_sha,
        item_ref=item_ref,
        require_any=require_any,
    )
    errors = requirement_issue_errors(
        issues, item_ref=item_ref, target_status="done",
    )
    if errors:
        return commit_sha, (
            "merge refused before the branch landed:\n" + "\n".join(errors)
        )
    return commit_sha, ""


__all__ = ["preflight"]
