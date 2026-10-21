"""How a remote pytest selection command follows a run and reports it.

:mod:`yoke_core.tools.pytest_remote_selection_run` follows every run it
adopts through :func:`follow`, whether it dispatched the selection, rejoined
it, or deferred to a full CI run on the same commit. Every line lands in the
pytest watcher's capture, so a red run carries each failed job's failure
region, and a run that outlives the turn watching it still has a recorded
wait that delivers its verdict.
"""

from __future__ import annotations

from yoke_core.domain.ci_job_outcome import CI_JOB_NOT_STARTED, REDISPATCH_RECOVERY
from yoke_core.tools.pytest_remote_selection import (
    EXIT_CANCELLED,
    EXIT_TIMED_OUT,
    EXIT_UNREACHABLE,
    LOCAL_FLAG,
    PREFIX,
)

#: Exit status per GitHub conclusion; the process mirrors the run.
CONCLUSION_EXIT = {
    "success": 0,
    "failure": 1,
    "timed_out": EXIT_TIMED_OUT,
    "cancelled": EXIT_CANCELLED,
    CI_JOB_NOT_STARTED: EXIT_CANCELLED,
}


def say(message: str) -> None:
    """Print one runner line under the remote-selection prefix."""
    print(f"{PREFIX} {message}", flush=True)


def relay_failed_log(*, project: str, repo: str, run_id: str) -> None:
    """Print every failed job's failure region so each shard's FAILED lines land.

    A sharded selection fails in several jobs at once, and the read below
    reports each of them separately, so the capture carries every failing
    shard rather than whichever one sorted last.
    """
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    result = _github_actions("failed-log", repo, run_id, project=project, timeout=180)
    text = (result.stdout or "").strip()
    if result.returncode != 0 or not text:
        detail = (result.stderr or "").strip() or "no output"
        say(
            f"failed-job logs unavailable ({detail}); inspect with "
            f"`yoke github-actions failed-log {repo} {run_id} --project {project}`"
        )
        return
    print(text, flush=True)


def record_wait(
    *, repo: str, run_id: str, head_sha: str, continue_command: str
) -> None:
    """Make this run's verdict reachable if the turn watching it ends.

    The watcher streaming this process dies with the turn that started it,
    so a worker that stops here would otherwise never learn the conclusion.
    Recording the wait hands that job to the control-plane sweep, and the
    line printed on success tells the caller it may end its turn instead of
    holding it. It is advisory: a run started outside a session records
    nothing, and a control plane that refuses says so without stopping the
    run.
    """
    from yoke_core.domain.session_ci_wait_record import (
        ambient_session_id,
        record_ci_run_wait,
    )
    from yoke_core.domain.session_ci_wait_schema import CI_WAIT_SELECTION

    if not ambient_session_id():
        return
    warning = record_ci_run_wait(
        repo=repo,
        run_id=run_id,
        kind=CI_WAIT_SELECTION,
        head_sha=head_sha,
        continue_command=continue_command,
    )
    if warning:
        say(f"{warning}; this run's verdict will not wake a stopped turn")
        return
    say(
        f"ci wait recorded for run {run_id}: if this watcher stops before the "
        "verdict, end the turn and do not poll GitHub; the verdict wakes this "
        f"session to run `{continue_command or 'the same command'}`"
    )


def await_conclusion(
    *,
    project: str,
    repo: str,
    run_id: str,
    timeout_seconds: int,
) -> str:
    """Poll the run to its end and name the conclusion GitHub reported."""
    from yoke_core.domain.deploy_pipeline_reporting import _poll_github_actions
    from yoke_core.domain.qa_case_ci_conclusion import conclusion_from_poll

    exit_code, output = _poll_github_actions(
        repo,
        run_id,
        timeout_seconds,
        project=project,
        sd=None,
    )
    conclusion = conclusion_from_poll(exit_code, output)
    if conclusion != "success" and output:
        print(output, flush=True)
    return conclusion


def follow(
    *,
    project: str,
    repo: str,
    run_id: str,
    source: str,
    head_sha: str,
    description: str,
    artifact_pattern: str,
    continue_command: str,
    timeout_seconds: int,
) -> int:
    """Await *run_id*, relay a red run's failure, and mirror the conclusion."""
    from yoke_core.domain.session_ci_wait_record import resolve_received_wait

    url = f"https://github.com/{repo}/actions/runs/{run_id}"
    record_wait(
        repo=repo,
        run_id=run_id,
        head_sha=head_sha,
        continue_command=continue_command,
    )
    say(f"{source} run={run_id} {url} head_sha={head_sha} {description}")
    conclusion = await_conclusion(
        project=project,
        repo=repo,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
    )
    if warning := resolve_received_wait(run_id=run_id, conclusion=conclusion):
        say(warning)
    if conclusion not in ("success", CI_JOB_NOT_STARTED):
        relay_failed_log(project=project, repo=repo, run_id=run_id)
    exit_code = CONCLUSION_EXIT.get(conclusion, EXIT_UNREACHABLE)
    recovery = ""
    if conclusion == CI_JOB_NOT_STARTED:
        recovery = f"; {REDISPATCH_RECOVERY}, or re-run with {LOCAL_FLAG}"
    elif conclusion not in ("success", "failure"):
        recovery = (
            "; the run reached no verdict — re-run the same command, which "
            f"dispatches a fresh run, or re-run with {LOCAL_FLAG}"
        )
    say(
        f"concluded {conclusion} exit={exit_code} run={run_id} {url} "
        f"ci_run_source={source}; full pytest output is one artifact per "
        f"shard: gh run download {run_id} -p '{artifact_pattern}'{recovery}"
    )
    return exit_code


__all__ = [
    "CONCLUSION_EXIT",
    "await_conclusion",
    "follow",
    "record_wait",
    "relay_failed_log",
    "say",
]
