"""Ask System Events to act from inside Terminal.app and name the outcome."""

from __future__ import annotations

from dataclasses import dataclass, field
import shlex
from typing import Any

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE,
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE,
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE,
    TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE,
    TERMINAL_WINDOW_ACCUMULATION_THRESHOLD,
)
from yoke_harness.ssh_mac_gui_session import (
    GUI_COMMAND_TIMEOUT_EXIT_CODE,
    run_terminal_app_command,
)
from yoke_harness.ssh_mac_host_session_state import read_terminal_window_count
from yoke_harness.ssh_mac_terminal_app import RunRemote


# Long enough for a granted probe on a loaded host, short enough that a
# missing grant (which blocks osascript on a consent prompt) fails fast.
AUTOMATION_PROBE_TIMEOUT_SECONDS = 15
# AppleScript's own "AppleEvent timed out", raised inside the probe.
_APPLE_EVENT_TIMEOUT = "-1712"
# AppleScript's "not authorized to send Apple events", the grant's denial.
_APPLE_EVENT_DENIED = "-1743"


@dataclass(frozen=True)
class TerminalAutomationProbe:
    """What a command inside Terminal saw when it asked System Events to act.

    A denial and a timeout have different fixes, so each carries its own error
    code. A timeout also reads Terminal's window count: with hundreds of
    windows left by earlier runs, every command inside Terminal stalls and the
    grant is not the cause.
    """

    error_code: str | None
    detail: str
    terminal_windows: int | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error_code is None


def _timeout_diagnostics(run: RunRemote) -> dict[str, Any]:
    """Snapshot live process state and bounded TCC history before cleanup."""
    commands = {
        "system_events_process": shlex.join(
            (
                "/bin/sh",
                "-c",
                'pids=$(/usr/bin/pgrep -x "System Events"); [ -n "$pids" ] || exit 1; '
                '/bin/ps -o pid,etime,stat -p "$(printf \'%s\' "$pids" | /usr/bin/tr "\\n" ,)"',
            )
        ),
        "tcc_log": shlex.join(
            (
                "/bin/zsh",
                "-o",
                "pipefail",
                "-c",
                "/usr/bin/log show --last 30s --style compact "
                "--predicate 'subsystem == \"com.apple.TCC\"' 2>&1 | /usr/bin/tail -c 8192",
            )
        ),
    }
    evidence: dict[str, Any] = {}
    for name, command in commands.items():
        try:
            result = run(command, timeout=5)
            evidence[name] = {
                "exit_code": result.returncode,
                "output": bounded_machine_qa_diagnostic(result.stdout),
                "stderr": bounded_machine_qa_diagnostic(result.stderr),
            }
            if result.returncode:
                evidence[name].update(
                    reason="terminal_automation_diagnostic_unavailable",
                    recovery="Check System Events process state, SSH and host log access; retry bridge-diagnose.",
                )
        except Exception as error:
            evidence[name] = {
                "reason": "terminal_automation_diagnostic_unavailable",
                "error_type": type(error).__name__,
                "recovery": "Check SSH and host log access; retry bridge-diagnose.",
            }
    return evidence


def terminal_system_events_automation(run: RunRemote) -> TerminalAutomationProbe:
    """Ask System Events to act from inside Terminal.app and name the outcome."""
    diagnostics: dict[str, Any] = {}

    def before_timeout() -> None:
        diagnostics.update(_timeout_diagnostics(run))

    def before_cleanup(result) -> None:
        text = (result.stderr or "") + (result.stdout or "")
        if not diagnostics and (
            result.returncode == GUI_COMMAND_TIMEOUT_EXIT_CODE
            or _APPLE_EVENT_TIMEOUT in text
        ):
            before_timeout()

    result = run_terminal_app_command(
        run,
        argv=(
            "/usr/bin/osascript",
            "-e",
            'tell application "System Events" to count processes',
        ),
        timeout=AUTOMATION_PROBE_TIMEOUT_SECONDS,
        on_timeout=before_timeout,
        on_result=before_cleanup,
    )
    if result.returncode == 0:
        return TerminalAutomationProbe(None, "")
    detail = (result.stderr or result.stdout or "").strip()[:200]
    if _APPLE_EVENT_DENIED in detail:
        return TerminalAutomationProbe(
            TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE,
            f"automation_missing:Terminal->System Events: {detail}",
        )
    timed_out = (
        result.returncode == GUI_COMMAND_TIMEOUT_EXIT_CODE
        or _APPLE_EVENT_TIMEOUT in detail
    )
    if not timed_out:
        return TerminalAutomationProbe(
            TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE,
            f"automation_failed:Terminal->System Events: exit "
            f"{result.returncode}: {detail}",
        )
    if not diagnostics:
        before_timeout()
    windows = read_terminal_window_count(run)
    if windows is not None and windows > TERMINAL_WINDOW_ACCUMULATION_THRESHOLD:
        return TerminalAutomationProbe(
            TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE,
            f"terminal_window_accumulation:{windows}: {detail}",
            windows,
            diagnostics,
        )
    return TerminalAutomationProbe(
        TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE,
        f"automation_timeout:Terminal->System Events: {detail}",
        windows,
        diagnostics,
    )


__all__ = [
    "AUTOMATION_PROBE_TIMEOUT_SECONDS",
    "TerminalAutomationProbe",
    "terminal_system_events_automation",
]
