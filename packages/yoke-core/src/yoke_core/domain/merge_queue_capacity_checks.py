"""Name required checks whose only red step was a runner-capacity refusal.

A shard whose runner is too slow refuses at
:data:`~yoke_core.domain.ci_job_outcome.CAPACITY_STEP` before pytest runs.
GitHub still concludes that check ``failure``, so a reader that classifies
by conclusion alone tells the holder to fix the lane for a check that never
reached a test verdict, and never offers the no-verdict rerun.

Every landing reader reads required checks through
:func:`yoke_core.domain.merge_github_check_runs.read_pr_landing_and_required_checks`,
which passes them through :func:`with_capacity_refusals`. A red required
check whose details URL names an Actions job is rewritten to
:data:`CAPACITY_REFUSED` when that job's only red step is the capacity
step. The run's jobs are read once per distinct run. Job evidence that
cannot be read — no Actions read access, a failed listing, a job missing
from it — proves nothing, so GitHub's conclusion stands.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any, Optional, Sequence

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)

from yoke_core.domain.ci_job_outcome import job_capacity_refused
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_actions_failed_jobs import list_run_jobs
from yoke_core.domain.merge_github_queue import resolve_auth_detail

if TYPE_CHECKING:
    from yoke_core.domain.merge_context import MergeContext
    from yoke_core.domain.merge_github_check_runs import LandingCheck

#: Conclusion of a required check whose job refused only for runner capacity.
CAPACITY_REFUSED = "capacity_refused"

#: Check conclusions a capacity refusal can arrive as.
_CAPACITY_CANDIDATE_CONCLUSIONS = frozenset({"failure", "timed_out"})

_JOB_URL = re.compile(r"/([^/]+/[^/]+)/actions/runs/(\d+)/job/(\d+)")


def _job_ref(check: "LandingCheck") -> Optional[tuple[str, str, str]]:
    """``(repo, run_id, job_id)`` for a red required check naming an Actions job."""
    if not check.required or check.conclusion not in _CAPACITY_CANDIDATE_CONCLUSIONS:
        return None
    match = _JOB_URL.search(check.url or "")
    return None if match is None else (match.group(1), match.group(2), match.group(3))


def with_capacity_refusals(
    ctx: "MergeContext", checks: Sequence["LandingCheck"]
) -> tuple["LandingCheck", ...]:
    """*checks* with each capacity-only red job's conclusion named as such."""
    checks = tuple(checks)
    if not any(_job_ref(check) for check in checks):
        return checks
    auth, auth_err = resolve_auth_detail(ctx, GITHUB_ACTIONS_READ_PERMISSION_LEVELS)
    if auth_err or auth is None:
        return checks
    jobs_by_run: dict[str, Optional[dict[str, Any]]] = {}
    rewritten = []
    for check in checks:
        ref = _job_ref(check)
        if ref is None or ref[0].lower() != auth.repo.lower():
            rewritten.append(check)
            continue
        _repo, run_id, job_id = ref
        if run_id not in jobs_by_run:
            try:
                listing = list_run_jobs(auth.repo, run_id, token=auth.token)
            except RestTransportError:
                listing = None
            jobs_by_run[run_id] = None if listing is None else {
                str(job.get("id")): job for job in listing if isinstance(job, dict)
            }
        job = (jobs_by_run[run_id] or {}).get(job_id)
        if job is not None and job_capacity_refused(job):
            check = dataclasses.replace(check, conclusion=CAPACITY_REFUSED)
        rewritten.append(check)
    return tuple(rewritten)


__all__ = ["CAPACITY_REFUSED", "with_capacity_refusals"]
