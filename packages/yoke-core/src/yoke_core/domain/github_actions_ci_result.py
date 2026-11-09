"""Canonical advisory result for a GitHub Actions CI run."""

from __future__ import annotations
from typing import Any, Dict, Optional
from pydantic import BaseModel

_RUNNING_STATUSES = frozenset({"queued", "in_progress", "pending", "waiting"})


class CheckCiResponse(BaseModel):
    # passed | failed | no_verdict | running | no_runs. The CLI adapter's
    # client-side wait loop additionally synthesizes "timeout" on budget
    # exhaustion. ``no_verdict`` is a completed run that is not a pass
    # and not a failing test (cancelled, skipped, empty conclusion, or
    # ``ci_job_not_started`` — a run whose jobs never got a runner).
    state: str
    run_id: Optional[int] = None
    html_url: Optional[str] = None
    status: Optional[str] = None
    conclusion: Optional[str] = None


def _classify(run: Optional[Dict[str, Any]]) -> CheckCiResponse:
    """Translate the latest ``workflow_runs[0]`` payload into a typed response."""
    if not run:
        return CheckCiResponse(state="no_runs")
    run_id = run.get("id")
    if not isinstance(run_id, int) or run_id <= 0:
        return CheckCiResponse(state="no_runs")

    status = str(run.get("status") or "").strip()
    conclusion = str(run.get("conclusion") or "").strip() or None
    html_url = str(run.get("html_url") or "").strip() or None

    if status == "completed":
        if conclusion == "success":
            state = "passed"
        elif conclusion == "failure":
            state = "failed"
        else:
            state = "no_verdict"
    elif status in _RUNNING_STATUSES:
        state = "running"
    elif status:
        state = "no_verdict"
    else:
        state = "no_runs"

    return CheckCiResponse(
        state=state,
        run_id=run_id,
        html_url=html_url,
        status=status or None,
        conclusion=conclusion,
    )
