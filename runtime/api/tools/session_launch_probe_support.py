"""Verdict failures and launched-session cleanup for launch probes.

Split from the mandate probe so the probe module stays the launch and verdict
path while this module owns what happens to the session afterwards.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence


FAILED_LAUNCH_STATES = frozenset({"failed", "cancelled", "expired", "outcome_unknown"})
TERMINATE_REASON = (
    "mandate acknowledgement probe verdict recorded; the case ends the "
    "session it launched"
)


#: The refusal a runner without operator mode or a steering seat receives
#: when it asks to end a session it does not own.
TERMINATION_AUTHORITY_REQUIRED = "TERMINATION_AUTHORITY_REQUIRED"


class ProbeFailure(Exception):
    """A named probe verdict failure, printed as ``code: detail``.

    ``refusal_code`` carries the registered command's own error code when a
    refused call named one, so a caller can tell an authority refusal from a
    broken command.
    """

    def __init__(self, code: str, detail: str, *, refusal_code: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.refusal_code = refusal_code


class _Client(Protocol):
    def call(
        self, args: Sequence[str], *, stdin: str | None = None
    ) -> dict[str, Any]: ...


def _session_ended(client: _Client, session_id: str) -> bool:
    rows = client.call(["sessions", "get", session_id]).get("rows") or []
    row = rows[0] if rows else {}
    return bool(row.get("ended_at") or row.get("terminated_at"))


def end_launched_session(
    client: _Client, launch_id: str
) -> tuple[str, ProbeFailure | None]:
    """End what the launch produced: its session, or the launch itself.

    Returns the named cleanup result and, only when cleanup genuinely broke,
    the failure. A session that already ended -- the launch instructions tell
    the native to end itself -- is left alone. A runner without termination
    authority leaves a live session running under a named result rather than
    failing a launch that already proved its verdict.
    """
    try:
        launch = (
            client.call(["session-control", "launch", "get", launch_id]).get("launch")
            or {}
        )
        registered = launch.get("registered_session_id")
        if registered:
            if _session_ended(client, str(registered)):
                return "launched session already ended", None
            try:
                client.call(
                    [
                        "sessions",
                        "terminate",
                        str(registered),
                        "--reason",
                        TERMINATE_REASON,
                    ]
                )
            except ProbeFailure as refused:
                if refused.refusal_code != TERMINATION_AUTHORITY_REQUIRED:
                    raise
                return (
                    "launched_session_left_running: this runner holds no "
                    f"termination authority ({TERMINATION_AUTHORITY_REQUIRED}); "
                    f"session {registered} was told to end itself, and an "
                    f"operator ends it with `yoke sessions terminate {registered} "
                    "--reason ...` if it does not",
                    None,
                )
            return "launched session ended", None
        if launch.get("state") not in FAILED_LAUNCH_STATES | {"succeeded"}:
            client.call(["session-control", "launch", "cancel", launch_id])
            return "unregistered launch cancelled", None
        return "launch closed without a session", None
    except ProbeFailure as failure:
        return "launched session not ended", ProbeFailure(
            "launched_session_not_ended",
            f"{failure}; end it with `yoke sessions terminate SESSION-ID --reason ...` "
            f"(`yoke session-control launch get {launch_id}` names the session)",
        )


__all__ = [
    "FAILED_LAUNCH_STATES",
    "ProbeFailure",
    "TERMINATE_REASON",
    "TERMINATION_AUTHORITY_REQUIRED",
    "end_launched_session",
]
