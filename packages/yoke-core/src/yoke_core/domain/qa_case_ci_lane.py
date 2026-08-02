"""Publish a lane branch and drive its CI workflow run.

The plumbing behind :mod:`yoke_core.domain.qa_case_ci_run`: resolve which
repository and branch the tree under test belongs to, publish it, then
dispatch and await the project's declared workflow.

Dispatch and await reuse the deployment layer's machinery
(:mod:`yoke_core.domain.deploy_pipeline_github_workflow_dispatch` and
:mod:`yoke_core.domain.deploy_pipeline_reporting`), which already owns
correlation-id dispatch with bounded ambiguity recovery — a lost dispatch
response is recovered by its GitHub-visible marker rather than reposted.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
from pathlib import Path
from typing import Iterator

from yoke_contracts.github_workflow_dispatch import (
    GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)

from yoke_core.domain.qa_case_execution import QaCaseExecutionError

#: Stage label passed to the shared poller; it names this gate in poll output.
POLL_LABEL = "verification-ci-gate"

_GITHUB_REMOTE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$"
)


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
            "executor dispatches a GitHub Actions workflow"
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
            f"checkout {checkout} is in detached HEAD; the CI executor "
            "dispatches a workflow against a named branch"
        )
    return branch


def push_lane(checkout: Path, branch: str) -> None:
    """Publish the lane branch so CI can check out the tree under test.

    Item branches stay local until merge, so the gate has to push before
    it can dispatch. ``--force-with-lease`` keeps a rebased or amended
    lane publishable without ever overwriting a remote branch this
    checkout has not seen; the preceding fetch is what gives the lease
    something to compare against, and it is best-effort because a first
    push has no remote branch to fetch.
    """
    _git(checkout, "fetch", "--quiet", "--no-tags", "origin", branch, timeout=300)
    _git_output(
        checkout, "push", "--force-with-lease", "origin",
        f"HEAD:refs/heads/{branch}",
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


@contextlib.contextmanager
def github_actions_authority() -> Iterator[None]:
    """Point GitHub Actions calls at the active control plane.

    The deployment layer selects its GitHub App authority from an explicit
    relay environment variable, because a deploy may hold an owner-only
    database connection while needing the sibling HTTPS plane for GitHub.
    A QA case is already running against whatever control plane the
    session is connected to, so when that connection is HTTPS it *is* the
    relay, and requiring a second variable would only be a way to forget
    one. An explicit selection always wins.
    """
    from yoke_core.domain.deploy_pipeline_reporting import (
        GITHUB_ACTIONS_RELAY_ENV,
    )

    preselected = (
        os.environ.get(GITHUB_ACTIONS_RELAY_ENV, "").strip()
        or os.environ.get(GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "").strip()
    )
    if preselected:
        yield
        return
    try:
        from yoke_cli.transport.https import resolve_https_connection

        https = resolve_https_connection()
    except Exception:
        https = None
    if https is None:
        yield
        return
    os.environ[GITHUB_ACTIONS_RELAY_ENV] = https.env
    try:
        yield
    finally:
        os.environ.pop(GITHUB_ACTIONS_RELAY_ENV, None)


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
    "dispatch_workflow",
    "github_actions_authority",
    "lane_branch",
    "push_lane",
    "repo_slug",
    "workflow_file",
]
