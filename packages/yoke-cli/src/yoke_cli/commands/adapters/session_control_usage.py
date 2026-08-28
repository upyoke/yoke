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
from yoke_cli.commands.adapters.session_control_keepalive import (
    SESSION_KEEPALIVE_HOLD_USAGE,
    SESSION_KEEPALIVE_RELEASE_USAGE,
)
from yoke_cli.commands.adapters.session_control_roster import SESSION_ROSTER_USAGE
from yoke_cli.commands.adapters.session_control_termination import (
    SESSION_TERMINATE_USAGE,
)
from yoke_cli.commands.adapters.session_control_wake import SESSION_WAKE_USAGE
from yoke_cli.commands.adapters.session_control_qualification import (
    QUALIFICATION_OPEN_USAGE,
)
from yoke_cli.commands.adapters.session_control_surface_policy import (
    SURFACE_POLICY_DISABLE_USAGE,
    SURFACE_POLICY_ENABLE_USAGE,
    SURFACE_POLICY_LIST_USAGE,
)


SESSION_CONTROL_USAGE_BY_FUNCTION_ID = {
    "session_control.qualification.open": QUALIFICATION_OPEN_USAGE,
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
    "session_control.keepalive.hold": SESSION_KEEPALIVE_HOLD_USAGE,
    "session_control.keepalive.release": SESSION_KEEPALIVE_RELEASE_USAGE,
    "session_control.session.terminate": SESSION_TERMINATE_USAGE,
    "session_control.session.wake": SESSION_WAKE_USAGE,
    "session_control.surface_policy.disable": SURFACE_POLICY_DISABLE_USAGE,
    "session_control.surface_policy.enable": SURFACE_POLICY_ENABLE_USAGE,
    "session_control.surface_policy.list": SURFACE_POLICY_LIST_USAGE,
    "sessions.list": SESSION_ROSTER_USAGE,
}


__all__ = ["SESSION_CONTROL_USAGE_BY_FUNCTION_ID"]
