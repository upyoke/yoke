"""Recover an idempotent QA dispatch through its existing HTTPS ledger replay."""

import sys

from yoke_cli.transport.https_relay_outcome import is_response_timeout
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_contracts.api.function_call import FunctionError


RESULT_WAIT_SECONDS = 600.0


def recover_dispatch_result(request, response, connection, *, relay):
    """Wait once on the same request reservation; never switch to a DB door.

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
        f"{RESULT_WAIT_SECONDS:g} seconds for its recorded result using the same request id.",
        file=sys.stderr, flush=True,
    )
    recovered, attempts = relay()
    if recovered.error is not None and recovered.error.code in {
        TRANSPORT_FAILED_CODE, "function_version_skew", "function_argument_version_skew",
    }:
        recovered = recovered.model_copy(update={"error": FunctionError(
            code="control_plane_connection_lost",
            message=f"qa_dispatch_result_unconfirmed: request {request.request_id}: "
                    f"{recovered.error.message}",
            recovery_hint="Read the deployment run and driver capture before re-driving "
                          "the same run; do not use --fresh or the database door.",
        )})
    return recovered, attempts
