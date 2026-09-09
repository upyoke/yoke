"""Recover a merge preflight that only lacks a commit-bound QA verdict.

Missing or stale ``verification_tree.head_sha`` on an otherwise passing
blocking run is recoverable only when the proof can be produced for the
candidate: stamp methodless hand acceptance onto the merging commit, or
re-execute SHA-bound Command cases against the lane head. Method-backed
substrate evidence keeps its runner authority and refuses with its supported
recovery path instead of being rebound by the merge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS
from yoke_core.domain.qa_terminal_settlement import BlockingRequirementIssue
from yoke_core.domain.standalone_item_merge_qa import evaluate, preflight


COMMIT_BOUND_STATES = frozenset({"stale-sha"})
COMMAND_RUNNERS = frozenset(
    str(method["runner_id"])
    for method in BUILTIN_QA_METHODS
    if method.get("proof_kind") == "command"
)


def is_commit_bound_refusal(issues: list[BlockingRequirementIssue]) -> bool:
    return bool(issues) and all(issue.state in COMMIT_BOUND_STATES for issue in issues)


def _requirement(item: dict[str, Any], requirement_id: str) -> dict[str, Any] | None:
    for row in item.get("qa_requirements") or []:
        if str(row.get("id")) == str(requirement_id):
            return row
    return None


def _mark_bound(requirement: dict[str, Any], commit_sha: str) -> None:
    requirement["recorded_head_sha"] = commit_sha
    requirement["verdict"] = "pass"
    requirement["completed_at"] = requirement.get("completed_at") or "recovered"
    if requirement.get("run_id") is None:
        requirement["run_id"] = 0


def rerecord_hand_run(requirement: dict[str, Any], commit_sha: str) -> None:
    """Persist a commit-bound hand verdict, then update the in-memory row."""
    from yoke_core.domain.qa_execution import cmd_run_add

    evidence = str(
        requirement.get("evidence")
        or requirement.get("raw_result")
        or "re-recorded against the merging commit"
    )
    cmd_run_add(
        requirement_id=int(requirement["id"]),
        performed_by="agent",
        verdict="pass",
        raw_result=evidence,
        head_sha=commit_sha,
    )
    _mark_bound(requirement, commit_sha)


def rerun_command_case(requirement_id: int) -> None:
    from yoke_core.domain.qa_case_execution import execute_case

    execute_case(int(requirement_id))


def _runner_authority_refusal(
    item: dict[str, Any],
    requirement: dict[str, Any],
    commit_sha: str,
) -> str:
    requirement_id = int(requirement["id"])
    method_id = str(requirement.get("method_id") or "<missing>")
    runner_id = str(requirement.get("runner_id") or "<missing>")
    public_ref = str(item.get("public_ref") or item.get("id") or "ITEM")
    transition = str(
        requirement.get("workflow_transition_id") or "<bound-transition>"
    )
    if runner_id == "browser_substrate":
        rerun_path = (
            f"`yoke qa case run --requirement-id {requirement_id} "
            "--base-url <candidate-url> --expected-branch <candidate-branch> "
            f"--expected-sha {commit_sha}`"
        )
    elif runner_id == "agent_mission":
        rerun_path = (
            f"`yoke qa plan run --item {public_ref} --transition {transition}`"
        )
    else:
        rerun_path = f"`yoke qa case run --requirement-id {requirement_id}`"
    return (
        "commit_bound_runner_authority: "
        f"requirement #{requirement_id} uses method {method_id!r} with runner "
        f"{runner_id!r}; merge recovery will not re-record or bind its "
        f"substrate-owned evidence to candidate commit {commit_sha}. Rerun the "
        "requirement through its registered runner against that candidate with "
        f"{rerun_path}, then retry `yoke merge item {public_ref}`. If the "
        "evidence exists only after "
        "deployment, select deployment posture and bind the requirement to the "
        "`done` transition with `qa_phase=post_deploy` or `manual_acceptance`; "
        "merge with `--skip-status`, run that phase through its registered "
        "runner, then close out."
    )


def recover_issues(
    item: dict[str, Any],
    issues: list[BlockingRequirementIssue],
    commit_sha: str,
    *,
    rerecord: Optional[Callable[[dict[str, Any], str], None]] = None,
    run_case: Optional[Callable[[int], None]] = None,
) -> str:
    """Apply recovery. Return an error string, or empty on success."""
    persist = rerecord or rerecord_hand_run
    execute = run_case or rerun_command_case
    for issue in issues:
        requirement = _requirement(item, issue.requirement_id)
        if requirement is None:
            return f"cannot recover requirement #{issue.requirement_id}: not on item"
        method_id = str(requirement.get("method_id") or "").strip()
        runner_id = str(requirement.get("runner_id") or "").strip()
        try:
            if runner_id in COMMAND_RUNNERS:
                execute(int(requirement["id"]))
                _mark_bound(requirement, commit_sha)
            elif not method_id and not runner_id:
                persist(requirement, commit_sha)
            else:
                return _runner_authority_refusal(item, requirement, commit_sha)
        except Exception as exc:
            return f"commit-bound recovery failed for #{issue.requirement_id}: {exc}"
    return ""


def recover_and_recheck(
    item: dict[str, Any],
    *,
    public_ref: str,
    repo_root: Path,
    branch: str,
    qa_error: str,
    rerecord: Optional[Callable[[dict[str, Any], str], None]] = None,
    run_case: Optional[Callable[[int], None]] = None,
) -> tuple[str, str]:
    """Recover a commit-bound preflight refusal, then re-run preflight."""
    commit_sha, issues, eval_error = evaluate(
        item, public_ref=public_ref, repo_root=repo_root, branch=branch,
    )
    if eval_error or not is_commit_bound_refusal(issues):
        return commit_sha, qa_error
    recover_error = recover_issues(
        item, issues, commit_sha, rerecord=rerecord, run_case=run_case,
    )
    if recover_error:
        return commit_sha, f"{qa_error}\n{recover_error}"
    return preflight(
        item, public_ref=public_ref, repo_root=repo_root, branch=branch,
    )


__all__ = [
    "COMMAND_RUNNERS",
    "COMMIT_BOUND_STATES",
    "is_commit_bound_refusal",
    "recover_and_recheck",
    "recover_issues",
    "rerecord_hand_run",
    "rerun_command_case",
]
