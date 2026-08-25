"""Operation inventory rows for session messaging, launch, and relay."""

from __future__ import annotations

from yoke_cli.operation_inventory_model import REASON_TOOL_SHAPED, _p, _Row, _w


WRAPPED_ROWS: tuple[_Row, ...] = (
    _w("yoke session-control qualification open", "session_control.qualification"),
    _w("yoke session-control message preview", "session_control.message"),
    _w("yoke session-control message send", "session_control.message"),
    _w("yoke session-control message list", "session_control.message"),
    _w("yoke session-control message get", "session_control.message"),
    _w("yoke session-control message acknowledge", "session_control.message"),
    _w("yoke session-control message cancel", "session_control.message"),
    _w("yoke session-control launch preview", "session_control.launch"),
    _w("yoke session-control launch create", "session_control.launch"),
    _w("yoke session-control launch get", "session_control.launch"),
    _w("yoke session-control launch list", "session_control.launch"),
    _w("yoke session-control launch cancel", "session_control.launch"),
    _w("yoke session-control launch retry", "session_control.launch"),
    _w("yoke session-control launch reconcile", "session_control.launch"),
    _w("yoke say", "session_control.message"),
    _w("yoke messages send", "session_control.message"),
    _w("yoke messages list", "session_control.message"),
    _w("yoke messages get", "session_control.message"),
    _w("yoke messages status", "session_control.message"),
    _w("yoke messages acknowledge", "session_control.message"),
    _w("yoke messages ack", "session_control.message"),
    _w("yoke messages cancel", "session_control.message"),
    _w("yoke sessions create", "session_control.launch"),
)

PERMANENT_ROWS: tuple[_Row, ...] = tuple(
    _p(f"yoke relay {verb}", "session_control.relay", REASON_TOOL_SHAPED)
    for verb in (
        "install",
        "uninstall",
        "status",
        "serve-once",
        "diagnostic",
        "probe-surface",
    )
) + (
    _p(
        "yoke session-control acceptance run",
        "session_control.acceptance",
        REASON_TOOL_SHAPED,
    ),
)


__all__ = ["PERMANENT_ROWS", "WRAPPED_ROWS"]
