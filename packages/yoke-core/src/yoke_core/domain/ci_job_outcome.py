"""What a completed GitHub Actions run's jobs say about the tree it checked.

A run's own conclusion cannot tell a red test from a run that never ran
one. When the runner pool is saturated, a job can sit queued until GitHub
cancels it, never assigned a runner and with no steps; the jobs that need
it are skipped, and the run concludes ``failure`` with no failed job at
all. Reporting that as a test failure sends the worker to fix a branch
nothing has examined, and adopting it as evidence wedges every gate at
that commit.

This is the one classifier every reader of a run applies — the run poll,
the wait and find reads, the CI check, and the control-plane wait sweep.
Each reads the run where the project's GitHub credentials live and
reports its *effective conclusion*: GitHub's conclusion, except
:data:`CI_JOB_NOT_STARTED` for a run whose jobs never started. That is a
named "no verdict", never ``failure``, and its recovery is to dispatch a
fresh run on the same commit.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

#: Effective conclusion of a run that never ran a job: no verdict.
CI_JOB_NOT_STARTED = "ci_job_not_started"

#: What a reader of a :data:`CI_JOB_NOT_STARTED` run does about it.
REDISPATCH_RECOVERY = (
    "no job got a runner, so this run reached no verdict about the tree; "
    "re-dispatch it: re-run the same command, which dispatches a fresh run "
    "on the same commit"
)

#: Job conclusions that are a red answer from a job that ran.
_RED_JOB_CONCLUSIONS = frozenset({"failure", "timed_out"})
#: Job conclusions a job can carry without ever having started.
_UNSTARTED_JOB_CONCLUSIONS = frozenset({"cancelled", "startup_failure"})


def job_started(job: Mapping[str, Any]) -> bool:
    """True once GitHub assigned the job a runner or recorded a step."""
    return bool(str(job.get("runner_name") or "").strip()) or bool(job.get("steps"))


def job_never_started(job: Mapping[str, Any]) -> bool:
    """A job that failed to start, or was cancelled before any runner took it."""
    conclusion = str(job.get("conclusion") or "")
    if conclusion == "startup_failure":
        return True
    return conclusion in _UNSTARTED_JOB_CONCLUSIONS and not job_started(job)


def effective_conclusion(
    conclusion: str,
    jobs: Optional[Sequence[Mapping[str, Any]]],
) -> str:
    """The conclusion a completed run reports once its jobs are read.

    ``jobs`` is ``None`` when they could not be read; GitHub's conclusion
    then stands, because missing job evidence proves nothing. A red job
    keeps the run red however many others never started — red is a real
    answer about the tree.
    """
    if conclusion in ("", "success"):
        return conclusion
    if conclusion == "startup_failure":
        return CI_JOB_NOT_STARTED
    if jobs is None:
        return conclusion
    if any(str(job.get("conclusion") or "") in _RED_JOB_CONCLUSIONS for job in jobs):
        return conclusion
    if not jobs or any(job_never_started(job) for job in jobs):
        return CI_JOB_NOT_STARTED
    return conclusion


def with_effective_conclusion(
    repo: str,
    run: Optional[Mapping[str, Any]],
    *,
    token: str,
) -> Optional[dict[str, Any]]:
    """Copy of a run payload whose ``conclusion`` is the effective one.

    Jobs are read only for a completed run that did not succeed, so an
    in-flight or green run costs no extra request.
    """
    if not isinstance(run, Mapping):
        return None
    copied = dict(run)
    conclusion = str(copied.get("conclusion") or "").strip()
    run_id = copied.get("id")
    if str(copied.get("status") or "") != "completed" or conclusion in ("", "success"):
        return copied
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_failed_jobs import list_run_jobs

    jobs: Optional[list] = None
    if run_id:
        try:
            jobs = list_run_jobs(repo, run_id, token=token)
        except RestTransportError:
            jobs = None
    copied["conclusion"] = effective_conclusion(conclusion, jobs)
    return copied


__all__ = [
    "CI_JOB_NOT_STARTED",
    "REDISPATCH_RECOVERY",
    "effective_conclusion",
    "job_never_started",
    "job_started",
    "with_effective_conclusion",
]
