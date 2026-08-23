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

RELAY_FUNCTION_IDS = (
    "session_control.relay.list",
    "session_control.relay.claim",
    "session_control.relay.report",
)

SESSION_CONTROL_FUNCTION_IDS = (
    *MESSAGE_FUNCTION_IDS,
    *LAUNCH_FUNCTION_IDS,
    *RELAY_FUNCTION_IDS,
)

__all__ = [
    "LAUNCH_FUNCTION_IDS",
    "MESSAGE_FUNCTION_IDS",
    "RELAY_FUNCTION_IDS",
    "SESSION_CONTROL_FUNCTION_IDS",
]
