"""Recover a merge preflight that only lacks a commit-bound QA verdict.

Missing or stale ``verification_tree.head_sha`` on an otherwise passing
blocking run is recoverable only when the proof can be produced for the
candidate: stamp methodless hand acceptance onto the merging commit, or
re-execute SHA-bound Command cases against the lane head. Method-backed
substrate evidence keeps its runner authority and refuses with its supported
recovery path instead of being rebound by the merge.

A Command case may move the lane before it tests it: the CI gate rebases the
lane onto its base and publishes the result. The candidate the merge resolved
before recovery is then superseded, so the recheck reads the item again and
binds to the lane's current head rather than reporting the old commit as
proven and landing it.
"""

from __future__ import annotations

import contextlib
import io

from pathlib import Path
from typing import Any, Callable, Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS
from yoke_core.domain.qa_terminal_settlement import BlockingRequirementIssue
from yoke_core.domain.standalone_item_merge_lane import merge_source_lane
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


def _runs_case(item: dict[str, Any], issue: BlockingRequirementIssue) -> bool:
    requirement = _requirement(item, issue.requirement_id) or {}
    return str(requirement.get("runner_id") or "").strip() in COMMAND_RUNNERS


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
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.epic_review import _epic_connect, review_insert

    # Item detail does not project ownership; read the writer's canonical row.
    with _epic_connect() as conn:
        owner = query_one(
            conn,
            "SELECT item_id, epic_id, task_num FROM qa_requirements WHERE id = %s",
            (int(requirement["id"]),),
        )
        if owner is None:
            raise ValueError(f"requirement #{requirement['id']} no longer exists")
        if (
            not owner["item_id"]
            and owner["epic_id"] is not None
            and owner["task_num"] is not None
        ):
            review_insert(
                conn,
                str(owner["epic_id"]),
                int(owner["task_num"]),
                "PASS",
                evidence,
                head_sha=commit_sha,
            )
        else:
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
    public_ref = str(item.get("public_ref") or "<public-ref-unavailable>")
    transition = str(requirement.get("workflow_transition_id") or "<bound-transition>")
    if runner_id == "browser_substrate":
        rerun_path = (
            f"`yoke qa case run --requirement-id {requirement_id} "
            "--base-url <candidate-url> --expected-branch <candidate-branch> "
            f"--expected-sha {commit_sha}`"
        )
    elif runner_id == "agent_mission":
        rerun_path = f"`yoke qa plan run --item {public_ref} --transition {transition}`"
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
    failures = []
    recovered = []
    for issue in issues:
        requirement = _requirement(item, issue.requirement_id)
        if requirement is None:
            failures.append(f"requirement #{issue.requirement_id}: not on item")
            continue
        method_id = str(requirement.get("method_id") or "").strip()
        runner_id = str(requirement.get("runner_id") or "").strip()
        diagnostic = io.StringIO()
        try:
            if runner_id in COMMAND_RUNNERS:
                # The case records the head it tested; the recheck reads it.
                execute(int(requirement["id"]))
            elif not method_id and not runner_id:
                with contextlib.redirect_stderr(diagnostic):
                    persist(requirement, commit_sha)
            else:
                failures.append(
                    _runner_authority_refusal(item, requirement, commit_sha)
                )
                continue
            recovered.append(str(issue.requirement_id))
        except (Exception, SystemExit) as exc:
            reason = diagnostic.getvalue().strip() or str(exc)
            failures.append(f"requirement #{issue.requirement_id}: {reason}")
    if failures:
        public_ref = str(item.get("public_ref") or "<public-ref-unavailable>")
        return (
            "commit_bound_recovery_failed: "
            + "; ".join(failures)
            + f". Recovered requirement ids: {', '.join(recovered) or 'none'}. "
            "Repair the named refusals, inspect each failed requirement with "
            "`yoke qa run list --requirement-id <id>`, then retry "
            f"`yoke merge item {public_ref}`; successful writes remain recorded."
        )
    return ""


def at_lane_head(
    item: dict[str, Any], *, repo_root: Path, branch: str
) -> dict[str, Any]:
    """Bind the merge source to what the branch carries now.

    The gate's rebase skips head recording, so the item's lane row can still
    name the commit the gate replaced; the branch ref is what it tested.
    """
    head = git.head_of(str(repo_root), branch)
    lane = merge_source_lane(item)
    if head and lane is not None:
        lane["commit_sha"] = head
    return item


def recover_and_recheck(
    item: dict[str, Any],
    *,
    public_ref: str,
    repo_root: Path,
    branch: str,
    qa_error: str,
    reload: Callable[[], tuple[dict[str, Any], str]],
    rerecord: Optional[Callable[[dict[str, Any], str], None]] = None,
    run_case: Optional[Callable[[int], None]] = None,
) -> tuple[str, str]:
    """Recover a commit-bound preflight refusal, then re-run preflight.

    ``reload`` returns a fresh merge-phase item read, or why it failed. It is
    used once a Command case ran, because that case's verdict and the lane
    head it tested exist only in the records it wrote.
    """
    commit_sha, issues, eval_error = evaluate(
        item,
        public_ref=public_ref,
        repo_root=repo_root,
        branch=branch,
    )
    if eval_error or not is_commit_bound_refusal(issues):
        return commit_sha, qa_error
    recover_error = recover_issues(
        item,
        issues,
        commit_sha,
        rerecord=rerecord,
        run_case=run_case,
    )
    if recover_error:
        return commit_sha, f"{qa_error}\n{recover_error}"
    if any(_runs_case(item, issue) for issue in issues):
        fresh, read_error = reload()
        if read_error:
            return commit_sha, (
                f"commit_bound_recheck_unreadable: the re-run case finished but "
                f"{public_ref} could not be read again to bind the merge to the "
                f"head it tested ({read_error}). Nothing was landed; restore the "
                f"item read, then retry `yoke merge item {public_ref}`."
            )
        item = at_lane_head(fresh, repo_root=repo_root, branch=branch)
    return preflight(
        item,
        public_ref=public_ref,
        repo_root=repo_root,
        branch=branch,
    )


__all__ = [
    "COMMAND_RUNNERS",
    "COMMIT_BOUND_STATES",
    "at_lane_head",
    "is_commit_bound_refusal",
    "recover_and_recheck",
    "recover_issues",
    "rerecord_hand_run",
    "rerun_command_case",
]
