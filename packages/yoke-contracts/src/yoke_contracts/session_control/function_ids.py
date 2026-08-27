"""Closed registered-function vocabulary for session control."""

MESSAGE_FUNCTION_IDS = (
    "session_control.message.preview",
    "session_control.message.send",
    "session_control.message.list",
    "session_control.message.get",
    "session_control.message.acknowledge",
    "session_control.message.cancel",
    "session_control.message.lease",
)

LAUNCH_FUNCTION_IDS = (
    "session_control.launch.preview",
    "session_control.launch.create",
    "session_control.launch.get",
    "session_control.launch.list",
    "session_control.launch.cancel",
    "session_control.launch.retry",
    "session_control.launch.reconcile",
)

RELAY_LIST_FUNCTION_ID = "session_control.relay.list"
RELAY_CLAIM_FUNCTION_ID = "session_control.relay.claim"
RELAY_REPORT_FUNCTION_ID = "session_control.relay.report"
#: The machine's report that a session's native process is verifiably gone.
RELAY_LIVENESS_FUNCTION_ID = "session_control.relay.liveness"

RELAY_FUNCTION_IDS = (
    RELAY_LIST_FUNCTION_ID,
    RELAY_CLAIM_FUNCTION_ID,
    RELAY_REPORT_FUNCTION_ID,
    RELAY_LIVENESS_FUNCTION_ID,
)

QUALIFICATION_FUNCTION_IDS = ("session_control.qualification.open",)

SESSION_FUNCTION_IDS = (
    "session_control.session.terminate",
    "session_control.session.wake",
)

SESSION_CONTROL_FUNCTION_IDS = (
    *MESSAGE_FUNCTION_IDS,
    *LAUNCH_FUNCTION_IDS,
    *RELAY_FUNCTION_IDS,
    *QUALIFICATION_FUNCTION_IDS,
    *SESSION_FUNCTION_IDS,
)

__all__ = [
    "LAUNCH_FUNCTION_IDS",
    "MESSAGE_FUNCTION_IDS",
    "QUALIFICATION_FUNCTION_IDS",
    "RELAY_CLAIM_FUNCTION_ID",
    "RELAY_FUNCTION_IDS",
    "RELAY_LIST_FUNCTION_ID",
    "RELAY_LIVENESS_FUNCTION_ID",
    "RELAY_REPORT_FUNCTION_ID",
    "SESSION_FUNCTION_IDS",
    "SESSION_CONTROL_FUNCTION_IDS",
]
