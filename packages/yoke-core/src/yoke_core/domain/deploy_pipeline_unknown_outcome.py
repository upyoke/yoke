"""Stop the deploy driver resumably when a write has no answer or the run stays busy."""

from functools import wraps
import sys
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_core.domain.function_connection_loss import CONNECTION_LOST_CODE

UNKNOWN_CODES = frozenset({TRANSPORT_FAILED_CODE, CONNECTION_LOST_CODE})


class DeploymentOutcomeUnknown(RuntimeError):
    """No authoritative answer; never settle this attempt as failed or retry it."""

    def __init__(self, run_id, function_id, request_id, detail):
        self.code = "deployment_outcome_unknown"
        super().__init__(
            f"{self.code}: {function_id} request {request_id or 'unreported'} on run {run_id} "
            f"has no confirmed outcome: {detail}. No retry or failure transition was issued. "
            f"Read `yoke deployment-runs get {run_id}` and the driver's capture; wait for "
            "the preparation receipt or reconcile the existing provider attempt before re-driving "
            "this same run. Do not use --fresh for response loss."
        )


class DeploymentRunStayedBusy(DeploymentOutcomeUnknown):
    """Every retry found the run busy; stop resumably and change nothing.

    A subclass so every path that already leaves the run and its pending
    receipt untouched for an unknown outcome does the same here.
    """

    def __init__(self, run_id, function_id, attempts, detail):
        RuntimeError.__init__(
            self,
            f"deployment_run_stayed_busy: {function_id} on run {run_id} was refused "
            f"as busy on all {attempts} attempts: {detail} The run was left "
            "unchanged in its current stage and was not failed. Re-drive it with "
            f"`yoke watch deploy -- {run_id}` once the holder named above finishes.",
        )
        self.code = "deployment_run_stayed_busy"


def preserve_unknown_outcome(function):
    """Stop the driver without changing a pending receipt or run status."""

    @wraps(function)
    def run(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DeploymentOutcomeUnknown as exc:
            print(str(exc), file=sys.stderr, flush=True)
            return 1

    return run
