"""Resume a failed GitHub workflow stage by walking its recorded dispatches.

A correlated stage dispatch is keyed by a request id, and a request id whose
run already reached a verdict replays it, so CI waits stay idempotent. A
plain re-drive of a failed stage would therefore only re-read the failure.

Resuming a run that failed at this stage walks the stage's recorded dispatch
chain instead: the base request id, then ``retry:<failed GitHub run id>``
after each run that failed. The dispatch intent store already records which
GitHub run each request id started. The walk joins the first run that is
still active or succeeded, and dispatches only past a run that failed. So
repeated resumes join one retry, and a run still going after a poll timeout
is joined rather than deployed a second time.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

#: More failed retries than this under one stage means something is wrong
#: with the walk itself, not with one more transient GitHub failure.
MAX_RETRY_HOPS = 50

Trigger = Callable[[str], tuple[Any, str, Optional[bool]]]


class RetryWalkError(RuntimeError):
    """The failed stage's dispatch chain could not be walked."""


def retry_scope(failed_run_id: str) -> str:
    """The request-id scope one retry of *failed_run_id* dispatches under."""
    return f"retry:{failed_run_id}"


def run_failed(
    github_actions: Callable[..., Any],
    github_repo: str,
    ga_run_id: str,
    *,
    project: str,
    sd: Optional[str],
) -> bool:
    """True when the GitHub run concluded failed; False when active or green."""
    result = github_actions("poll", github_repo, ga_run_id, project=project, sd=sd)
    if result.returncode == 1:
        return True
    if result.returncode in (0, 2, 3):
        return False
    detail = (result.stderr or result.stdout or "").strip() or "no diagnostic"
    raise RetryWalkError(
        f"could not read the state of workflow run {ga_run_id} while resuming "
        f"its failed stage (exit {result.returncode}): {detail}. Nothing was "
        "dispatched; restore GitHub Actions read authority, then resume the "
        "run again."
    )


def walk_failed_stage_dispatch(
    trigger: Trigger,
    *,
    github_actions: Callable[..., Any],
    github_repo: str,
    project: str,
    sd: Optional[str],
) -> tuple[Any, str]:
    """Dispatch a failed stage once, or join the retry already started.

    *trigger* dispatches or recovers the request id for one scope and returns
    ``(result, ga_run_id, dispatched)``. A new POST, a failed trigger or an
    unnamed outcome ends the walk with that answer.
    """
    scope = ""
    for _ in range(MAX_RETRY_HOPS):
        result, ga_run_id, dispatched = trigger(scope)
        if result.returncode != 0 or not ga_run_id or dispatched is not False:
            return result, ga_run_id
        if not run_failed(
            github_actions, github_repo, ga_run_id, project=project, sd=sd
        ):
            print(f"  Resume joins workflow run {ga_run_id}")
            return result, ga_run_id
        scope = retry_scope(ga_run_id)
        print(f"  Workflow run {ga_run_id} failed; resuming under {scope}")
    raise RetryWalkError(
        f"the failed stage's dispatch chain passed {MAX_RETRY_HOPS} failed "
        "retries without reaching a new dispatch. Inspect the stage's workflow "
        "runs, fix the repeated cause, then resume with `--fresh`."
    )


def dispatch_stage(
    trigger: Trigger,
    scope: str,
    *,
    walk: bool,
    github_actions: Callable[..., Any],
    github_repo: str,
    project: str,
    sd: Optional[str],
) -> tuple[Any, str, str]:
    """Return ``(result, ga_run_id, walk_error)`` for one stage dispatch.

    *walk* resumes a failed correlated stage through its dispatch chain. A
    stage already dispatching under an explicit scope (``--fresh``, a stale
    run's successor) triggers under that scope directly.
    """
    if not walk or scope:
        result, ga_run_id, _dispatched = trigger(scope)
        return result, ga_run_id, ""
    try:
        result, ga_run_id = walk_failed_stage_dispatch(
            trigger,
            github_actions=github_actions,
            github_repo=github_repo,
            project=project,
            sd=sd,
        )
    except RetryWalkError as exc:
        return None, "", str(exc)
    return result, ga_run_id, ""


__all__ = [
    "MAX_RETRY_HOPS",
    "RetryWalkError",
    "dispatch_stage",
    "retry_scope",
    "run_failed",
    "walk_failed_stage_dispatch",
]
