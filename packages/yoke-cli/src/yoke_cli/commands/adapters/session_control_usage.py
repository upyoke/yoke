"""Usage lines contributed by the registered session-control family."""

from __future__ import annotations

from yoke_cli.commands.adapters.session_control_launches import (
    LAUNCH_CANCEL_USAGE,
    LAUNCH_CREATE_USAGE,
    LAUNCH_GET_USAGE,
    LAUNCH_LIST_USAGE,
    LAUNCH_PREVIEW_USAGE,
    LAUNCH_RECONCILE_USAGE,
    LAUNCH_RETRY_USAGE,
)
from yoke_cli.commands.adapters.session_control_messages import (
    MESSAGE_ACKNOWLEDGE_USAGE,
    MESSAGE_CANCEL_USAGE,
    MESSAGE_GET_USAGE,
    MESSAGE_LIST_USAGE,
    MESSAGE_PREVIEW_USAGE,
    MESSAGE_SEND_USAGE,
)
from yoke_cli.commands.adapters.session_control_roster import SESSION_ROSTER_USAGE


SESSION_CONTROL_USAGE_BY_FUNCTION_ID = {
    "session_control.message.preview": MESSAGE_PREVIEW_USAGE,
    "session_control.message.send": MESSAGE_SEND_USAGE,
    "session_control.message.list": MESSAGE_LIST_USAGE,
    "session_control.message.get": MESSAGE_GET_USAGE,
    "session_control.message.acknowledge": MESSAGE_ACKNOWLEDGE_USAGE,
    "session_control.message.cancel": MESSAGE_CANCEL_USAGE,
    "session_control.launch.preview": LAUNCH_PREVIEW_USAGE,
    "session_control.launch.create": LAUNCH_CREATE_USAGE,
    "session_control.launch.get": LAUNCH_GET_USAGE,
    "session_control.launch.list": LAUNCH_LIST_USAGE,
    "session_control.launch.cancel": LAUNCH_CANCEL_USAGE,
    "session_control.launch.retry": LAUNCH_RETRY_USAGE,
    "session_control.launch.reconcile": LAUNCH_RECONCILE_USAGE,
    "sessions.list": SESSION_ROSTER_USAGE,
}


__all__ = ["SESSION_CONTROL_USAGE_BY_FUNCTION_ID"]
