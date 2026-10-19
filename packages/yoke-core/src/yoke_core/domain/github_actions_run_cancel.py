"""Cancel one GitHub Actions workflow run with an already resolved token.

This is ordinary cancellation, not force-cancel: GitHub still runs a cancelled
job's ``if: cancelled()`` steps, and that is where a workflow releases what it
started — the release bridge cancels the promotion it dispatched there.
Force-cancel skips those steps, so it is reserved for a run that ordinary
cancellation could not stop.

A run that concluded before the request arrived is already settled: GitHub
answers 409, a re-read shows ``completed``, and the answer is
:data:`ALREADY_COMPLETED` rather than a failure.
"""

from __future__ import annotations

from yoke_core.domain import github_actions_rest
from yoke_core.domain.gh_rest_transport import RestTransportError


CANCEL_REQUESTED = "cancel_requested"
ALREADY_COMPLETED = "already_completed"


class RunCancelError(RuntimeError):
    """GitHub refused to cancel a run that is still active."""


def run_completed(*, repo: str, run_id: str, token: str) -> bool:
    """True when the run reads back as completed; an unreadable run is not."""
    try:
        refreshed = github_actions_rest.rest_get(
            f"/repos/{repo}/actions/runs/{run_id}", token=token
        )
    except RestTransportError:
        return False
    return (
        isinstance(refreshed, dict)
        and str(refreshed.get("status") or "") == "completed"
    )


def cancel_run(*, repo: str, run_id: str, token: str) -> str:
    """Request cancellation of one run; return what GitHub settled on."""
    try:
        github_actions_rest.rest_post(
            f"/repos/{repo}/actions/runs/{run_id}/cancel",
            body={},
            token=token,
        )
    except RestTransportError as exc:
        if exc.status in {409, 422} and run_completed(
            repo=repo, run_id=run_id, token=token
        ):
            return ALREADY_COMPLETED
        raise RunCancelError(
            f"GitHub refused to cancel workflow run {run_id} in {repo}: {exc}"
        ) from exc
    return CANCEL_REQUESTED


__all__ = [
    "ALREADY_COMPLETED",
    "CANCEL_REQUESTED",
    "RunCancelError",
    "cancel_run",
    "run_completed",
]
