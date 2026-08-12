"""Publish a lane branch and drive its CI workflow run.

The plumbing behind :mod:`yoke_core.domain.qa_case_ci_run`: resolve which
repository and branch the tree under test belongs to, publish it, then
dispatch and await the project's declared workflow.

Dispatch and await reuse the deployment layer's machinery
(:mod:`yoke_core.domain.deploy_pipeline_github_workflow_dispatch` and
:mod:`yoke_core.domain.deploy_pipeline_reporting`), which already owns
correlation-id dispatch with bounded ambiguity recovery — a lost dispatch
response is recovered by its GitHub-visible marker rather than reposted.

Which control plane relays those calls is a separate question, answered by
:mod:`yoke_core.domain.qa_case_ci_authority` and re-exported here so the
lane stays one import for its callers.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from pathlib import Path

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)

from yoke_core.domain.qa_case_ci_authority import (
    GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV as GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
    github_actions_authority as github_actions_authority,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

#: Stage label passed to the shared poller; it names this gate in poll output.
POLL_LABEL = "verification-ci-gate"

_GITHUB_REMOTE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class WorkflowRun:
    """Completed GitHub workflow run eligible to cover a QA case."""

    run_id: str
    status: str
    conclusion: str
    html_url: str
    head_sha: str


def _git(
    checkout: Path,
    *args: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git_output(checkout: Path, *args: str, what: str, timeout: int = 120) -> str:
    result = _git(checkout, *args, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise QaCaseExecutionError(f"{what} failed: {detail}")
    return result.stdout.strip()


def repo_slug(checkout: Path) -> str:
    """Return ``owner/name`` for the checkout's ``origin`` remote.

    The lane branch is pushed to ``origin`` and the workflow is dispatched
    in that same repository, so the remote is the authority here — a
    separately configured repo slug could name somewhere the branch does
    not exist.
    """
    url = _git_output(
        checkout, "remote", "get-url", "origin",
        what="reading the origin remote",
    )
    match = _GITHUB_REMOTE.search(url)
    if match is None:
        raise QaCaseExecutionError(
            f"origin remote {url!r} is not a GitHub repository; the CI "
            "runner dispatches a GitHub Actions workflow"
        )
    return f"{match['owner']}/{match['name']}"


def lane_branch(case: dict, checkout: Path) -> str:
    """Return the branch the workflow should run against."""
    branch = str(case.get("lane_branch") or "").strip()
    if branch and branch != "null":
        return branch
    branch = _git_output(
        checkout, "rev-parse", "--abbrev-ref", "HEAD",
        what="resolving the checkout's current branch",
    )
    if branch == "HEAD":
        raise QaCaseExecutionError(
            f"checkout {checkout} is in detached HEAD; the CI runner "
            "dispatches a workflow against a named branch"
        )
    return branch


def checked_out_branch(checkout: Path) -> str:
    """Return the checkout's current branch, or ``HEAD`` when detached."""
    return _git_output(
        checkout, "rev-parse", "--abbrev-ref", "HEAD",
        what="resolving the checkout's current branch",
    )


def ref_sha(checkout: Path, ref: str) -> str:
    """Resolve the immutable commit CI will check out."""
    return _git_output(
        checkout, "rev-parse", f"{ref}^{{commit}}",
        what=f"resolving CI source ref {ref!r}",
    )


def push_lane(checkout: Path, branch: str, *, source_ref: str = "HEAD") -> None:
    """Publish the lane branch so CI can check out the tree under test.

    Item branches stay local until merge, so the gate has to push before
    it can dispatch. ``source_ref`` may be the recorded lane commit after
    local cleanup; CI binds to that commit, not to the checkout directory.
    ``--force-with-lease`` keeps a rebased or amended lane publishable without
    ever overwriting a remote branch this
    checkout has not seen; the preceding fetch is what gives the lease
    something to compare against, and it is best-effort because a first
    push has no remote branch to fetch.
    """
    _git(checkout, "fetch", "--quiet", "--no-tags", "origin", branch, timeout=300)
    _git_output(
        checkout, "push", "--force-with-lease", "origin",
        f"{source_ref}:refs/heads/{branch}",
        what=f"pushing lane branch {branch!r} to origin",
        timeout=600,
    )


def workflow_file(case: dict) -> str:
    """Return the declared CI workflow filename for this case."""
    workflow = str(case["method_config"].get("ci_workflow") or "").strip()
    if not workflow:
        raise QaCaseExecutionError(
            "CI cases require method_config.ci_workflow — the filename of "
            "the project's required-status-check workflow. Declare the "
            "project's 'ci_workflow_file' capability and re-register its "
            "verification command, or bind this plan case to the local "
            "'command' method instead."
        )
    return workflow


def find_pull_request_run(
    *,
    project: str,
    repo: str,
    workflow: str,
    head_sha: str,
    timeout_seconds: int,
    status: str = "completed",
) -> WorkflowRun | None:
    """Return the PR run for the exact source commit, if any.

    ``status`` narrows the lookup to runs in that state; passing ``""``
    asks for the newest run whatever it is doing, which is what a gate
    that just opened the pull request needs — the entry run it is waiting
    for has not concluded yet.
    """
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    status_args = ("--status", status) if status else ()
    result = _github_actions(
        "find-run", repo, workflow, head_sha,
        "--event", "pull_request", *status_args, "--json",
        project=project, sd=None, timeout=timeout_seconds,
    )
    try:
        response = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        detail = (result.stderr or result.stdout or "").strip()
        raise QaCaseExecutionError(
            f"could not query pull-request runs for {workflow} "
            f"on {repo}@{head_sha[:12]}: {detail or 'invalid response'}"
        ) from exc
    payload = response.get("result") if isinstance(response, dict) else None
    if result.returncode == 1 and isinstance(payload, dict):
        if not payload.get("found"):
            return None
    if result.returncode != 0 or not isinstance(payload, dict):
        detail = (result.stderr or result.stdout or "").strip()
        raise QaCaseExecutionError(
            f"could not query pull-request runs for {workflow} "
            f"on {repo}@{head_sha[:12]}: {detail or 'lookup failed'}"
        )
    if not payload.get("found"):
        return None
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise QaCaseExecutionError(
            "pull-request workflow lookup returned no run id"
        )
    return WorkflowRun(
        run_id=run_id,
        status=str(payload.get("status") or "").strip(),
        conclusion=str(payload.get("conclusion") or "").strip(),
        html_url=str(payload.get("html_url") or "").strip(),
        head_sha=str(payload.get("head_sha") or "").strip(),
    )


def dispatch_workflow(
    *,
    project: str,
    repo: str,
    workflow: str,
    branch: str,
    request_id: str,
    timeout_seconds: int,
) -> str:
    """Dispatch *workflow* against *branch* and return its GitHub run id."""
    from yoke_core.domain.deploy_pipeline_github_workflow_dispatch import (
        trigger_with_recovery_retries,
    )
    from yoke_core.domain.deploy_pipeline_github_workflow_reconciliation import (
        _trigger_args,
    )
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    args = _trigger_args(
        repo, workflow, branch, {},
        request_id=request_id,
        correlation_input=WORKFLOW_DISPATCH_CORRELATION_INPUT,
    )
    result = trigger_with_recovery_retries(
        args,
        github_actions=_github_actions,
        project=project,
        sd=None,
        timeout_sec=timeout_seconds,
    )
    run_id = result.stdout.strip()
    if result.returncode != 0 or not run_id:
        detail = (result.stderr or result.stdout or "").strip()
        raise QaCaseExecutionError(
            f"could not dispatch {workflow} on {repo}@{branch}: "
            f"{detail or 'no run id returned'}"
        )
    return run_id


def run_head_sha(*, project: str, repo: str, run_id: str) -> str:
    """The commit a workflow run checked out, read through the same relay.

    Reading this back is what turns "a run concluded" into "the tree under
    test concluded", so it has to reach GitHub the way dispatch and polling
    already do — through the control plane holding the App credentials.
    Resolving a token on this machine instead would require private-key
    material that only exists server-side.

    Returns ``""`` when the relay answers without the field, which is what
    a control plane older than the field looks like; the caller names that
    degradation rather than treating it as a failure.
    """
    import json

    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    result = _github_actions(
        "poll", repo, run_id, "--json", project=project,
    )
    try:
        envelope = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise QaCaseExecutionError(
            f"could not read run {run_id} on {repo}: unparseable relay "
            f"response ({exc})"
        ) from exc
    if not isinstance(envelope, dict) or not envelope.get("success"):
        detail = (result.stderr or result.stdout or "").strip()
        raise QaCaseExecutionError(
            f"could not read run {run_id} on {repo}: "
            f"{detail or 'relay reported no result'}"
        )
    payload = envelope.get("result")
    if not isinstance(payload, dict):
        raise QaCaseExecutionError(
            f"run read for {run_id} on {repo} returned no result object"
        )
    return str(payload.get("head_sha") or "").strip()


def await_workflow(
    *, project: str, repo: str, run_id: str, timeout_seconds: int,
) -> tuple[int, str]:
    """Block until the run concludes; return ``(exit_code, poll_output)``."""
    from yoke_core.domain.deploy_pipeline_reporting import _poll_github_actions

    return _poll_github_actions(
        repo, run_id, timeout_seconds, POLL_LABEL, project=project, sd=None,
    )


__all__ = [
    "POLL_LABEL",
    "await_workflow",
    "checked_out_branch",
    "dispatch_workflow",
    "find_pull_request_run",
    "github_actions_authority",
    "run_head_sha",
    "lane_branch",
    "push_lane",
    "ref_sha",
    "repo_slug",
    "workflow_file",
    "WorkflowRun",
]
