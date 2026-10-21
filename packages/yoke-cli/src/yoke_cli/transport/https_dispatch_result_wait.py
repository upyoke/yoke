"""Recover an idempotent QA dispatch through its existing HTTPS ledger replay."""

import sys

from yoke_cli.transport.https_relay_outcome import is_response_timeout
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_cli.transport.function_version_skew import (
    ARGUMENT_SKEW_ERROR_CODE, SKEW_ERROR_CODE,
)
from yoke_contracts.api.function_call import FunctionError


RESULT_WAIT_SECONDS = 60.0
RESULT_WAIT_ATTEMPTS = 10


def recover_dispatch_result(request, response, connection, *, relay):
    """Wait on the same request reservation; never switch to a DB door.

    The server serializes the original and this identical request, then reads
    its recorded result. Failed originals may run again: QA dispatch is itself
    idempotent. An unanswered recovery leaves the driver resumable.
    """
    if (
        request.function != "deployment_runs.qa_stage.dispatch"
        or not request.request_id
        or not is_response_timeout(response)
    ):
        return response, 0
    print(
        f"Waiting by design: HTTPS QA dispatch request {request.request_id} "
        f"on {connection.env!r} exceeded its response limit; waiting up to "
        f"{RESULT_WAIT_SECONDS * RESULT_WAIT_ATTEMPTS:g} seconds for its recorded "
        "result using the same request id in bounded HTTPS waits.",
        file=sys.stderr, flush=True,
    )
    attempts = 0
    for _ in range(RESULT_WAIT_ATTEMPTS):
        recovered, used = relay()
        attempts += used
        if recovered.error is None or recovered.error.code != TRANSPORT_FAILED_CODE:
            break
    if recovered.error is not None and recovered.error.code in {
        TRANSPORT_FAILED_CODE, SKEW_ERROR_CODE, ARGUMENT_SKEW_ERROR_CODE,
    }:
        recovered = recovered.model_copy(update={"error": FunctionError(
            code="control_plane_connection_lost",
            message=f"qa_dispatch_result_unconfirmed: request {request.request_id}: "
                    f"{recovered.error.message}",
            recovery_hint="Read the deployment run and driver capture before re-driving "
                          "the same run; do not use --fresh or the database door.",
        )})
    return recovered, attempts
