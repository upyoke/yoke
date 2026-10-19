"""Return an unstarted job through the durable relay report path."""

from yoke_contracts.session_control.function_ids import RELAY_REPORT_FUNCTION_ID
from yoke_harness.session_relay_outcomes import ServeOnceJobOutcome
from yoke_harness.session_relay_report_delivery import (
    RELAY_REPORT_TIMEOUT_SECONDS,
    deliver_terminal_report,
)


def release_claimed_job(inventory, job, reason, *, dispatcher, state_dir):
    response = deliver_terminal_report(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        {
            "relay_id": inventory.relay_id,
            "machine_id": inventory.machine_id,
            "job_kind": job["job_kind"],
            "job_id": job["job_id"],
            "lease_id": job["lease_id"],
            "result": "released",
            "evidence": {
                "result_code": reason,
                "recovery": "The job is eligible for the next relay claim; no native started.",
            },
        },
        state_dir=state_dir,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    success = bool(getattr(response, "success", False))
    error = getattr(response, "error", None)
    return ServeOnceJobOutcome(
        "reported" if success else "report_failed",
        str(job["job_kind"]),
        str(job["job_id"]),
        "released",
        None
        if success
        else str(getattr(error, "code", None) or "release_report_failed"),
    )
