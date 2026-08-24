"""Watch every GitHub Actions run for one exact commit until it concludes.

This exists as a command because a poll filter written at the call site
compares the wrong things, and does it silently. One hand-authored loop
matched a hash it had expanded from an abbreviated SHA rather than
resolved through ``git rev-parse``, and keyed on the run's display title
rather than the workflow's name. Neither mistake announces itself: the
loop keeps polling a set that can never match, so a finished run reads
exactly like a running one.

Resolution and matching therefore live here, once: the ref is resolved
with ``git rev-parse <ref>^{commit}``, which yields one full object id
for a branch, a tag, ``HEAD``, or an abbreviated SHA alike; the run set
comes from the REST ``head_sha`` query, re-checked against each returned
``head_sha``; and a workflow name is compared against each run's ``name``
field, which is the workflow's own name rather than the run title.

Reads follow :data:`CI_SUITE_SCHEDULE` so concurrent sessions share the
project's GitHub budget. Every state change, every terminal conclusion,
and both deadline cases emit a line, because a watcher that goes quiet is
indistinguishable from one whose subject is still working. REST
dispatches through the project's GitHub App auth.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_contracts.project_defaults import default_project_for_directory
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_actions_rest import rest_get
from yoke_core.domain.github_poll_schedule import (
    CI_SUITE_SCHEDULE,
    next_read_delay,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)

EXIT_SUCCESS = 0
EXIT_CONCLUDED_FAILURE = 1
EXIT_USAGE = 2
EXIT_STILL_RUNNING = 3
#: Shared with the rest of the Actions surface (see
#: :mod:`yoke_core.domain.github_actions`) so one code means one thing
#: across every command that resolves project GitHub auth.
EXIT_AUTH = 4
EXIT_NO_RUN_FOUND = 5

DEFAULT_TIMEOUT_SECONDS = 1800
#: How long to wait for a run to REGISTER before accepting that the commit
#: runs nothing. A just-pushed commit reports no runs for a few seconds
#: while GitHub creates them, so accepting the first empty read would call
#: every fresh push "no CI".
DEFAULT_APPEARANCE_TIMEOUT_SECONDS = 90

COMPLETED_STATUS = "completed"
SUCCESS_CONCLUSION = "success"

Emit = Callable[[str], None]
FetchRuns = Callable[[], List[Dict[str, Any]]]


class CommitResolutionError(RuntimeError):
    """Raised when a ref does not name a commit in this checkout."""


def resolve_commit(ref: str, *, cwd: Path) -> str:
    """Return the full object id *ref* names, via ``git rev-parse``.

    The ``^{commit}`` peel is what makes one call correct for every input
    shape a caller passes — branch, tag, ``HEAD``, or abbreviated SHA —
    and what keeps an abbreviated SHA from being "expanded" by string
    padding into a hash that matches nothing.
    """
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )
    resolved = completed.stdout.strip()
    if completed.returncode != 0 or not resolved:
        raise CommitResolutionError(
            f"'{ref}' does not name a commit in {cwd}"
        )
    return resolved


def matching_runs(
    repo: str,
    head_sha: str,
    workflow_name: str,
    *,
    token: str,
    get: Callable[..., Any] = rest_get,
) -> List[Dict[str, Any]]:
    """Return the runs for exactly *head_sha*, narrowed to *workflow_name*.

    The ``head_sha`` equality re-check is deliberate belt-and-braces: the
    query already filters server-side, and this module's whole purpose is
    that a run for a neighbouring commit must never satisfy a wait.
    """
    data = get(
        f"/repos/{repo}/actions/runs",
        query={"head_sha": head_sha, "per_page": "100"},
        token=token,
    )
    if not isinstance(data, dict):
        return []
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        return []
    selected: List[Dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if str(run.get("head_sha") or "") != head_sha:
            continue
        if workflow_name and str(run.get("name") or "") != workflow_name:
            continue
        selected.append(run)
    return selected


def _run_label(run: Dict[str, Any]) -> str:
    """Name a run by its workflow and id, never by its display title."""
    name = str(run.get("name") or "").strip() or "(unnamed workflow)"
    return f"{name} #{run.get('id')}"


def watch_commit_runs(
    *,
    head_sha: str,
    ref: str,
    repo: str,
    workflow_name: str,
    fetch_runs: FetchRuns,
    emit: Emit,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    appearance_timeout_seconds: float = DEFAULT_APPEARANCE_TIMEOUT_SECONDS,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Poll until every matched run concludes, or a deadline passes.

    Emits one line per observed state change, one per conclusion, and one
    for each deadline outcome, then returns the exit code describing what
    happened. A transient REST failure is reported and retried rather than
    ending the watch — the deadline is what bounds it.
    """
    selector = workflow_name or "(any)"
    emit(
        f"CI run target: repo={repo} sha={head_sha} ref={ref} "
        f"workflow={selector}"
    )

    start = now()
    last_status: Dict[Any, str] = {}
    conclusions: Dict[Any, str] = {}
    appeared = False

    while True:
        elapsed = int(now() - start)
        try:
            runs = fetch_runs()
        except RestTransportError as exc:
            emit(f"Error: failed to read runs for {head_sha}: {exc}")
            runs = []

        if runs:
            appeared = True

        for run in runs:
            run_id = run.get("id")
            status = str(run.get("status") or "").strip()
            url = str(run.get("html_url") or "")
            if last_status.get(run_id) != status:
                last_status[run_id] = status
                emit(
                    f"CI run status: {_run_label(run)} {status} "
                    f"(elapsed: {elapsed}s) {url}".rstrip()
                )
            if status == COMPLETED_STATUS and run_id not in conclusions:
                conclusion = str(run.get("conclusion") or "").strip() or "unknown"
                conclusions[run_id] = conclusion
                emit(
                    f"CI run concluded: {_run_label(run)} {conclusion} "
                    f"(elapsed: {elapsed}s) {url}".rstrip()
                )

        # Compare the live run set against what has concluded, rather than
        # counting: a run that drops out of a later listing would otherwise
        # leave the counts unequal forever and wait out the deadline.
        current_ids = {run.get("id") for run in runs}
        if runs and current_ids <= set(conclusions):
            verdicts = [conclusions[run_id] for run_id in current_ids]
            failed = sorted(
                value for value in verdicts if value != SUCCESS_CONCLUSION
            )
            if failed:
                emit(
                    f"CI run verdict: {len(failed)} of {len(verdicts)} run(s) "
                    f"did not succeed ({', '.join(failed)})"
                )
                return EXIT_CONCLUDED_FAILURE
            emit(f"CI run verdict: all {len(verdicts)} run(s) succeeded")
            return EXIT_SUCCESS

        if not appeared:
            deadline = min(timeout_seconds, appearance_timeout_seconds)
            if elapsed >= deadline:
                emit(
                    f"CI run not found: no run for {head_sha} appeared "
                    f"within {int(deadline)}s"
                )
                return EXIT_NO_RUN_FOUND
            emit(
                f"CI run has not appeared yet (elapsed: {elapsed}s, "
                f"appearance timeout: {int(deadline)}s)"
            )
        elif elapsed >= timeout_seconds:
            pending = len(last_status) - len(conclusions)
            emit(
                f"CI run timeout: {pending} run(s) still running after "
                f"{int(timeout_seconds)}s"
            )
            return EXIT_STILL_RUNNING

        sleep(next_read_delay(elapsed, CI_SUITE_SCHEDULE))


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="github_actions_commit_run_watch",
        description=(
            "Watch every GitHub Actions run for one exact commit until it "
            "concludes. The ref is resolved through git rev-parse and runs "
            "are matched on the resolved head SHA, so an abbreviated SHA or "
            "a branch name is as exact as a full object id."
        ),
    )
    parser.add_argument(
        "ref",
        nargs="?",
        default="HEAD",
        help="Branch, tag, SHA, or HEAD (default) to resolve and watch.",
    )
    parser.add_argument(
        "--workflow",
        default="",
        help="Workflow name to narrow to; omit to watch every run for the "
        "commit. Matched against the workflow's name, not the run title.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project whose GitHub binding supplies the repository and "
        "token. Defaults to the project owning the working directory.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Seconds to wait for conclusions (default {DEFAULT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--appearance-timeout",
        type=float,
        default=DEFAULT_APPEARANCE_TIMEOUT_SECONDS,
        help="Seconds to wait for a run to register before reporting that "
        f"the commit runs nothing (default {DEFAULT_APPEARANCE_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Checkout to resolve the ref in (defaults to the working "
        "directory).",
    )
    return parser.parse_args(list(argv))


def _emit(line: str) -> None:
    print(line, flush=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ns = _parse_args(sys.argv[1:] if argv is None else argv)
    cwd = (ns.repo_root or Path.cwd()).resolve()

    try:
        head_sha = resolve_commit(ns.ref, cwd=cwd)
    except CommitResolutionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    project = ns.project or default_project_for_directory(cwd)
    try:
        auth = resolve_project_github_auth(
            project,
            required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        print(f"Error: {exc.code}: {exc}", file=sys.stderr)
        print(f"  Repair: {repair_command_hint(exc, project)}", file=sys.stderr)
        return EXIT_AUTH

    def fetch_runs() -> List[Dict[str, Any]]:
        return matching_runs(
            auth.repo, head_sha, ns.workflow, token=auth.token,
        )

    return watch_commit_runs(
        head_sha=head_sha,
        ref=ns.ref,
        repo=auth.repo,
        workflow_name=ns.workflow,
        fetch_runs=fetch_runs,
        emit=_emit,
        timeout_seconds=ns.timeout,
        appearance_timeout_seconds=ns.appearance_timeout,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
