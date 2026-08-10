"""CI-routed post-rebase verification for the merge boundary.

When the candidate tree differs from covering QA evidence and the project
declares a ``ci_workflow_file`` capability, the merge gate pushes the
integrated candidate to the item lane, dispatches that workflow, waits for
the conclusion, asserts the CI-reported head matches the candidate tree,
and records a ``qa_runs`` row so a later same-tree attempt can skip.

Routing frees the local machine and the machine-wide admission slot; wall
clock while holding the merge lock is comparable to a local run (CI is
often a few minutes longer). Pass ``--local-verification`` for deliberate
offline local execution — never a silent fallback when CI is unreachable.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional, Tuple

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import qa_case_ci_lane, verification_tree_binding
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.engines import merge_worktree_tree_coverage
from yoke_core.engines.merge_worktree_prepare import MergeContext

_CONCLUSION_PATTERN = re.compile(r"failed:\s*(?P<conclusion>[a-z_]+)")
DEFAULT_MERGE_CI_TIMEOUT_SECONDS = 5400


def _parent():
    from yoke_core.engines import merge_worktree as _mw

    return _mw


def _ci_conclusion(exit_code: int, output: str) -> str:
    if exit_code == 0:
        return "success"
    match = _CONCLUSION_PATTERN.search(output.casefold())
    if match:
        conclusion = match.group("conclusion")
        return (
            conclusion
            if conclusion
            in {
                "cancelled",
                "failure",
                "neutral",
                "skipped",
                "stale",
                "startup_failure",
                "success",
                "timed_out",
            }
            else "failure"
        )
    if "timed out" in output.casefold():
        return "timed_out"
    return "error"


def _project_ci_workflow_file(project: str) -> str:
    """Read the declared CI workflow through the connected control plane."""
    response = call_dispatcher(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "cap_type": "ci_workflow_file"},
    )
    if not response.success:
        code = (response.error.code if response.error else "unknown") or "unknown"
        if code == "not_found":
            return ""
        message = (response.error.message if response.error else "") or "read failed"
        raise RuntimeError(f"CI workflow capability read failed ({code}): {message}")
    raw = str((response.result or {}).get("settings_json") or "{}")
    try:
        settings = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("CI workflow capability returned invalid JSON") from exc
    if not isinstance(settings, dict):
        raise RuntimeError("CI workflow capability must be a JSON object")
    return str(settings.get("workflow_file") or "").strip()


def _should_route_ci(ctx: MergeContext) -> bool:
    """True when CI routing applies (declared workflow, no local override)."""
    args = getattr(ctx, "args", None)
    if getattr(args, "local_verification", False):
        return False
    project = getattr(ctx, "project", None)
    if not project:
        return False
    return bool(_project_ci_workflow_file(str(project)))


def _fetch_ci_head_sha(*, project: str, repo: str, ci_run_id: str) -> str:
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    from yoke_core.domain.github_actions_rest import workflow_run_head_sha
    from yoke_core.domain.project_github_auth import resolve_project_github_auth

    auth = resolve_project_github_auth(
        project,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    return workflow_run_head_sha(repo, ci_run_id, token=auth.token)


def _record_ci_run(
    ctx: MergeContext,
    *,
    scope: str,
    command: str,
    workflow: str,
    verdict: str,
    raw_result: str,
    duration_ms: int,
) -> Optional[int]:
    item_id_raw = getattr(ctx, "item_id", None)
    try:
        item_id = int(str(item_id_raw))
    except (TypeError, ValueError):
        return None
    resp = call_dispatcher(
        function_id="merge.tests.record_post_rebase_ci_run",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "scope": scope,
            "command": command,
            "workflow": workflow,
            "verdict": verdict,
            "raw_result": raw_result,
            "duration_ms": duration_ms,
            "executor_type": "ci_run",
        },
    )
    if not resp.success:
        code = (resp.error.code if resp.error else "unknown") or "unknown"
        message = (resp.error.message if resp.error else "") or ""
        raise RuntimeError(
            f"merge-gate CI evidence recording failed ({code}): {message}"
        )
    result = resp.result or {}
    return int(result["qa_run_id"]) if result.get("qa_run_id") is not None else None


def run_ci_verification(
    ctx: MergeContext,
    *,
    scope: str,
    command: str,
) -> Optional[Tuple[int, str]]:
    """Push the candidate, run project CI, record evidence. None on success."""
    mw = _parent()
    _print = mw._print
    cwd = Path(ctx.worktree_path)
    project = str(ctx.project or "")
    workflow = _project_ci_workflow_file(project)
    if not workflow:
        _print(
            "Error: CI verification selected but project has no declared "
            "ci_workflow_file capability.",
            err=True,
        )
        return (1, "ci workflow undeclared")

    branch = str(getattr(ctx.args, "branch", "") or "").strip()
    if not branch:
        _print("Error: merge CI verification requires a named lane branch.", err=True)
        return (1, "ci lane branch missing")

    tree = verification_tree_binding.resolve_tree_identity(cwd)
    if tree is None or not tree.head_sha:
        _print(
            "Error: could not resolve candidate tree identity for CI verification.",
            err=True,
        )
        return (1, "ci tree identity unavailable")

    _print("")
    _print(
        f"[phase:tests] routing registered verification ({scope}) to CI "
        f"({workflow}); frees local admission slot — wall-clock while holding "
        "the merge lock is comparable to a local run"
    )
    started = time.monotonic()
    ci_run_id = ""
    repo = ""
    try:
        repo = qa_case_ci_lane.repo_slug(cwd)
        qa_case_ci_lane.push_lane(cwd, branch, source_ref="HEAD")
        with qa_case_ci_lane.github_actions_authority():
            ci_run_id = qa_case_ci_lane.dispatch_workflow(
                project=project,
                repo=repo,
                workflow=workflow,
                branch=branch,
                request_id=f"merge-gate:{ctx.item_id}:{tree.head_sha}",
                timeout_seconds=DEFAULT_MERGE_CI_TIMEOUT_SECONDS,
            )
            exit_code, poll_output = qa_case_ci_lane.await_workflow(
                project=project,
                repo=repo,
                run_id=ci_run_id,
                timeout_seconds=DEFAULT_MERGE_CI_TIMEOUT_SECONDS,
            )
        ci_head = _fetch_ci_head_sha(
            project=project,
            repo=repo,
            ci_run_id=ci_run_id,
        )
        if not ci_head:
            raise QaCaseExecutionError(f"CI run {ci_run_id} did not report a head_sha")
        candidate_tree = merge_worktree_tree_coverage._tree_object_id(cwd, "HEAD")
        ci_tree = merge_worktree_tree_coverage._tree_object_id(cwd, ci_head)
        if candidate_tree is None or ci_tree is None or candidate_tree != ci_tree:
            raise QaCaseExecutionError(
                f"CI head sha {ci_head} does not resolve to the candidate "
                f"tree (candidate={candidate_tree}, ci={ci_tree})"
            )
        covered = verification_tree_binding.TreeIdentity(str(cwd), ci_head)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        raw_result = json.dumps(
            {
                "repo": repo or None,
                "workflow": workflow,
                "branch": branch,
                "ci_run_id": ci_run_id or None,
                "ci_conclusion": "error",
                "failure_class": "infrastructure_transient",
                "error": str(exc),
                "verification_tree": tree.as_payload(),
            },
            sort_keys=True,
        )
        try:
            run_id = _record_ci_run(
                ctx,
                scope=scope,
                command=command,
                workflow=workflow,
                verdict="error",
                raw_result=raw_result,
                duration_ms=duration_ms,
            )
        except Exception as record_exc:  # noqa: BLE001 - still block the merge
            _print(
                f"Error: CI unreachable or failed ({exc}); also could not "
                f"record evidence ({record_exc})",
                err=True,
            )
            return (1, "ci unreachable")
        _print(
            f"Error: CI verification unreachable or failed; recorded QA run "
            f"#{run_id}: {exc}",
            err=True,
        )
        return (1, "ci unreachable")

    duration_ms = int((time.monotonic() - started) * 1000)
    conclusion = _ci_conclusion(exit_code, poll_output)
    run_url = f"https://github.com/{repo}/actions/runs/{ci_run_id}"
    verdict = "pass" if conclusion == "success" else "fail"
    raw_result = json.dumps(
        {
            "repo": repo,
            "workflow": workflow,
            "branch": branch,
            "ci_run_id": ci_run_id,
            "run_url": run_url,
            "exit_code": exit_code,
            "ci_conclusion": conclusion,
            "verification_tree": covered.as_payload(),
        },
        sort_keys=True,
    )
    try:
        run_id = _record_ci_run(
            ctx,
            scope=scope,
            command=command,
            workflow=workflow,
            verdict=verdict,
            raw_result=raw_result,
            duration_ms=duration_ms,
        )
    except Exception as exc:  # noqa: BLE001 - evidence failure blocks merge
        _print(f"Error: {exc}", err=True)
        return (1, "ci evidence recording failed")

    _print(f"[phase:tests] CI run {run_url} (qa_run #{run_id}, head {ci_head[:12]})")
    if verdict != "pass":
        _print(
            f"Tests failed after integration (CI conclusion={conclusion}).",
            err=True,
        )
        if poll_output:
            _print(poll_output, err=True)
        return (1, "tests failed")
    return None


__all__ = [
    "DEFAULT_MERGE_CI_TIMEOUT_SECONDS",
    "_should_route_ci",
    "run_ci_verification",
]
