"""Stop the deploy driver resumably when a write has no answer or the run stays busy."""

from functools import wraps
import sys
import time
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


#: Pauses between the three sends of an idempotent call whose answer was lost.
REDISPATCH_DELAYS_SECONDS = (5.0, 15.0)


def redispatch_after_connection_loss(call, *, run_id, function_id):
    """Re-send an idempotent call only while its answer is lost, then stop resumably.

    For a call that is safe to repeat -- QA stage dispatch creates
    requirements only when absent, recomputes its gate and keys its notices --
    a dropped connection need not end the driver. Only a lost answer is
    re-sent; a refusal is returned unchanged on its first answer.
    """
    for delay in (*REDISPATCH_DELAYS_SECONDS, None):
        response = call()
        error = None if response.success else response.error
        if error is None or error.code not in UNKNOWN_CODES:
            return response
        if delay is None:
            raise DeploymentOutcomeUnknown(
                run_id,
                function_id,
                response.request_id,
                f"{response.error.message} (lost on all "
                f"{len(REDISPATCH_DELAYS_SECONDS) + 1} sends)",
            )
        print(
            f"{function_id} lost its answer ({response.error.code}); "
            f"sending again in {delay:g}s",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)


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
