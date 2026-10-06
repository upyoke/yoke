"""What a remote pytest selection run reports beyond its own conclusion.

:mod:`yoke_core.tools.pytest_remote_selection_run` prints through these
helpers: every line lands in the pytest watcher's capture, so a red run
carries each failed job's failure region, and a run that outlives the
turn watching it still has a recorded wait that delivers its verdict.
"""

from __future__ import annotations

from yoke_core.tools.pytest_remote_selection import PREFIX


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
    Recording the wait hands that job to the control-plane sweep. It is
    advisory: a run started outside a session records nothing, and a
    control plane that refuses says so without stopping the run.
    """
    from yoke_core.domain.session_ci_wait_record import record_ci_run_wait
    from yoke_core.domain.session_ci_wait_schema import CI_WAIT_SELECTION

    warning = record_ci_run_wait(
        repo=repo,
        run_id=run_id,
        kind=CI_WAIT_SELECTION,
        head_sha=head_sha,
        continue_command=continue_command,
    )
    if warning:
        say(f"{warning}; this run's verdict will not wake a stopped turn")


__all__ = ["record_wait", "relay_failed_log", "say"]
