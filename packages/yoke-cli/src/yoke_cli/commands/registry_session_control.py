"""Registered and machine-local routes for fleet session control."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.session_control_acceptance import (
    ACCEPTANCE_RUN_USAGE,
    session_control_acceptance_run,
)
from yoke_cli.commands.adapters.session_control_launches import (
    session_launch_cancel,
    session_launch_create,
    session_launch_get,
    session_launch_list,
    session_launch_preview,
    session_launch_reconcile,
    session_launch_retry,
    sessions_create,
)
from yoke_cli.commands.adapters.session_control_messages import (
    say,
    session_message_acknowledge,
    session_message_cancel,
    session_message_get,
    session_message_list,
    session_message_preview,
    session_message_send,
)
from yoke_cli.commands.adapters.session_control_relay import (
    RELAY_DIAGNOSTIC_USAGE,
    RELAY_INSTALL_USAGE,
    RELAY_PROBE_SURFACE_USAGE,
    RELAY_SERVE_ONCE_USAGE,
    RELAY_SERVE_USAGE,
    RELAY_STATUS_USAGE,
    RELAY_UNINSTALL_USAGE,
    relay_diagnostic,
    relay_install,
    relay_probe_surface,
    relay_serve,
    relay_serve_once,
    relay_status,
    relay_uninstall,
)
from yoke_cli.commands.adapters.session_control_qualification import (
    session_qualification_open,
)
from yoke_cli.commands.adapters.session_control_roster import (
    session_control_roster_list,
)
from yoke_cli.commands.adapters.session_control_termination import (
    session_terminate,
)
from yoke_cli.commands.adapters.session_control_wake import session_wake
from yoke_cli.commands.adapters.session_control_surface_policy import (
    session_surface_policy_disable,
    session_surface_policy_enable,
    session_surface_policy_list,
)


AdapterFn = Callable[[List[str]], int]
RegisteredRoute = Tuple[str, AdapterFn]


SESSION_CONTROL_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], RegisteredRoute] = {
    ("session-control", "qualification", "open"): (
        "session_control.qualification.open",
        session_qualification_open,
    ),
    ("session-control", "message", "preview"): (
        "session_control.message.preview",
        session_message_preview,
    ),
    ("session-control", "message", "send"): (
        "session_control.message.send",
        session_message_send,
    ),
    ("session-control", "message", "list"): (
        "session_control.message.list",
        session_message_list,
    ),
    ("session-control", "message", "get"): (
        "session_control.message.get",
        session_message_get,
    ),
    ("session-control", "message", "acknowledge"): (
        "session_control.message.acknowledge",
        session_message_acknowledge,
    ),
    ("session-control", "message", "cancel"): (
        "session_control.message.cancel",
        session_message_cancel,
    ),
    ("session-control", "launch", "preview"): (
        "session_control.launch.preview",
        session_launch_preview,
    ),
    ("session-control", "launch", "create"): (
        "session_control.launch.create",
        session_launch_create,
    ),
    ("session-control", "launch", "get"): (
        "session_control.launch.get",
        session_launch_get,
    ),
    ("session-control", "launch", "list"): (
        "session_control.launch.list",
        session_launch_list,
    ),
    ("session-control", "launch", "cancel"): (
        "session_control.launch.cancel",
        session_launch_cancel,
    ),
    ("session-control", "launch", "retry"): (
        "session_control.launch.retry",
        session_launch_retry,
    ),
    ("session-control", "launch", "reconcile"): (
        "session_control.launch.reconcile",
        session_launch_reconcile,
    ),
    ("sessions", "list"): ("sessions.list", session_control_roster_list),
    ("session-control", "session", "terminate"): (
        "session_control.session.terminate",
        session_terminate,
    ),
    ("session-control", "session", "wake"): (
        "session_control.session.wake",
        session_wake,
    ),
    ("session-control", "surface-policy", "disable"): (
        "session_control.surface_policy.set",
        session_surface_policy_disable,
    ),
    ("session-control", "surface-policy", "enable"): (
        "session_control.surface_policy.clear",
        session_surface_policy_enable,
    ),
    ("session-control", "surface-policy", "list"): (
        "session_control.surface_policy.list",
        session_surface_policy_list,
    ),
}


SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY: Dict[Tuple[str, ...], RegisteredRoute] = {
    ("say",): ("session_control.message.send", say),
    ("messages", "send"): ("session_control.message.send", say),
    ("messages", "list"): (
        "session_control.message.list",
        session_message_list,
    ),
    ("messages", "get"): (
        "session_control.message.get",
        session_message_get,
    ),
    ("messages", "status"): (
        "session_control.message.get",
        session_message_get,
    ),
    ("messages", "acknowledge"): (
        "session_control.message.acknowledge",
        session_message_acknowledge,
    ),
    ("messages", "ack"): (
        "session_control.message.acknowledge",
        session_message_acknowledge,
    ),
    ("messages", "cancel"): (
        "session_control.message.cancel",
        session_message_cancel,
    ),
    ("sessions", "create"): (
        "session_control.launch.create",
        sessions_create,
    ),
    ("sessions", "terminate"): (
        "session_control.session.terminate",
        session_terminate,
    ),
}


SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("session-control", "acceptance", "run"): session_control_acceptance_run,
    ("relay", "diagnostic"): relay_diagnostic,
    ("relay", "install"): relay_install,
    ("relay", "probe-surface"): relay_probe_surface,
    ("relay", "uninstall"): relay_uninstall,
    ("relay", "status"): relay_status,
    ("relay", "serve-once"): relay_serve_once,
    ("relay", "serve"): relay_serve,
}

SESSION_CONTROL_TOOL_SHAPED_USAGE = {
    "yoke session-control acceptance run": ACCEPTANCE_RUN_USAGE,
    "yoke relay diagnostic": RELAY_DIAGNOSTIC_USAGE,
    "yoke relay install": RELAY_INSTALL_USAGE,
    "yoke relay probe-surface": RELAY_PROBE_SURFACE_USAGE,
    "yoke relay uninstall": RELAY_UNINSTALL_USAGE,
    "yoke relay status": RELAY_STATUS_USAGE,
    "yoke relay serve-once": RELAY_SERVE_ONCE_USAGE,
    "yoke relay serve": RELAY_SERVE_USAGE,
}


__all__ = [
    "SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY",
    "SESSION_CONTROL_SUBCOMMAND_REGISTRY",
    "SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS",
    "SESSION_CONTROL_TOOL_SHAPED_USAGE",
]
