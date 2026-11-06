"""Stop the deploy driver resumably when a write has no answer or the run stays busy."""

from functools import wraps
import sys
import time
from uuid import uuid4
from yoke_contracts.runtime_ports.relay_telemetry import get_relay_telemetry
from yoke_core.domain.function_connection_loss import CONNECTION_LOST_CODE
from yoke_core.domain.function_lock_refusal import (
    LOCK_RETRY_DELAYS_SECONDS,
    RETRYABLE_LOCK_CODES,
)


TRANSPORT_FAILED_CODE = get_relay_telemetry().TRANSPORT_FAILED_CODE

UNKNOWN_CODES = frozenset({TRANSPORT_FAILED_CODE, CONNECTION_LOST_CODE})
# The self-deploy database door wraps connection exceptions in this code.
READ_CONNECTION_CODES = UNKNOWN_CODES | {"handler_exception"}


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
    """Retry idempotent dispatch on lost answers or bounded lock contention.

    Busy answers and lost answers consume their own shared retry schedules.
    One request identity joins the same execution across every retry.
    Other refusals return immediately; exhaustion leaves the run resumable.
    """
    request_id = str(uuid4())
    lost_delays = iter(REDISPATCH_DELAYS_SECONDS)
    busy_delays = iter(LOCK_RETRY_DELAYS_SECONDS)
    attempts = 0
    losses = 0
    while True:
        response = call(request_id=request_id)
        attempts += 1
        error = None if response.success else response.error
        if error is not None and error.code in RETRYABLE_LOCK_CODES:
            delay = next(busy_delays, None)
            if delay is None:
                raise DeploymentRunStayedBusy(
                    run_id, function_id, attempts, error.message
                )
            diagnostic = f"answered {error.code}; asking again"
        elif error is not None and error.code in UNKNOWN_CODES:
            losses += 1
            delay = next(lost_delays, None)
            if delay is None:
                raise DeploymentOutcomeUnknown(
                    run_id, function_id, response.request_id,
                    f"{error.message} (lost on all {losses} sends)",
                )
            diagnostic = f"lost its answer ({error.code}); sending again"
        else:
            return response
        print(
            f"{function_id} {diagnostic} in {delay:g}s",
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
