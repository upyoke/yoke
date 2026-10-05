"""Read the host facts that decide whether the GUI bridge can work at all.

Each fact is read on its own and answers `True`, `False`, or `None` — the last
meaning the probe itself did not answer. Collapsing "not locked" into "could
not tell whether it is locked" is what turns a diagnosis into a guess, and the
recoveries differ: one sends a person to the screen, the other to the probe.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE,
    terminal_bridge_recovery,
)
from yoke_harness.ssh_mac_terminal_app import RunRemote, run_osascript


#: Terminal's own setting. While it is on, macOS refuses every synthetic
#: keystroke sent to Terminal, silently, so the window sits at its prompt while
#: the bridge reports the keys as delivered.
SECURE_KEYBOARD_ENTRY_DOMAIN = "com.apple.Terminal"
SECURE_KEYBOARD_ENTRY_KEY = "SecureKeyboardEntry"
SCREEN_SHARING_CURTAIN_RECOVERY = (
    "display is curtained by an active Screen Sharing connection; "
    "disconnect Screen Sharing (or reconnect without curtain) and retry"
)
SCREEN_SAVER_DEFAULT_IDLE_SECONDS = 20 * 60
SCREEN_SAVER_READ_COMMAND = "defaults -currentHost read com.apple.screensaver idleTime"
SCREEN_SAVER_DISABLE_COMMAND = (
    "defaults -currentHost write com.apple.screensaver idleTime -int 0"
)
SCREEN_SAVER_ENABLED_ERROR = "macos_screen_saver_enabled"
SCREEN_SAVER_PROBE_ERROR = "macos_screen_saver_probe_unavailable"


def read_console_user(run: RunRemote) -> str | None:
    """Return the login that owns the host's graphical session."""
    result = run("/usr/bin/stat -f%Su /dev/console", timeout=10)
    return result.stdout.strip() if result.returncode == 0 else None


def read_display_locked(run: RunRemote) -> bool | None:
    """Return whether the host's screen is locked."""
    result = run(
        "/usr/sbin/ioreg -n Root -d1",
        timeout=10,
    )
    if result.returncode:
        return None
    # macOS nests this flag in IOConsoleUsers; -k hides that parent property.
    return (
        re.search(r'"CGSSessionScreenIsLocked"\s*=\s*Yes\b', result.stdout) is not None
    )


def read_load_average(run: RunRemote) -> float | None:
    """Return the host's one-minute load average."""
    result = run("/usr/sbin/sysctl -n vm.loadavg", timeout=10)
    if result.returncode:
        return None
    fields = result.stdout.replace("{", " ").replace("}", " ").split()
    for field in fields:
        try:
            return float(field)
        except ValueError:
            continue
    return None


def read_screen_sharing_active(run: RunRemote) -> bool | None:
    """Check for the macOS Screen Sharing processes that curtain a display."""
    result = run("/usr/bin/pgrep -x '(screensharingd|ScreensharingAgent)'", timeout=10)
    if result.returncode not in {0, 1}:
        return None
    return result.returncode == 0 and bool(result.stdout.strip())


def display_lock_recovery(context: dict[str, Any]) -> str:
    """Explain a confirmed curtain, otherwise retain the ordinary lock remedy."""
    recovery = (
        SCREEN_SHARING_CURTAIN_RECOVERY
        if context.get("screen_sharing_active") is True
        else terminal_bridge_recovery(TERMINAL_DISPLAY_LOCKED_ERROR_CODE)
    )
    idle = context.get("screen_saver_idle_seconds")
    if idle is not None and idle > 0:
        recovery += "; " + screen_saver_recovery(idle)
    elif "screen_saver_idle_seconds" in context and idle is None:
        recovery += "; " + screen_saver_recovery(None)
    return recovery


def read_screen_saver_idle_seconds(
    run: RunRemote, console_user: str | None
) -> int | None:
    """Read the console user's current-host preference without changing it."""
    if not console_user or console_user in {"root", "loginwindow", "_mbsetupuser"}:
        return None
    result = run("/usr/bin/" + SCREEN_SAVER_READ_COMMAND, timeout=10)
    if result.returncode:
        detail = (result.stderr or "") + (result.stdout or "")
        if "idleTime" in detail and "does not exist" in detail:
            return SCREEN_SAVER_DEFAULT_IDLE_SECONDS
        return None
    try:
        idle = int(result.stdout.strip())
    except ValueError:
        return None
    return idle if idle >= 0 else None


def screen_saver_recovery(idle_seconds: int | None) -> str:
    """Teach the explicit operator action for an enabled or unreadable saver."""
    if idle_seconds is None:
        return (
            "screen saver idle time could not be read; run "
            + SCREEN_SAVER_READ_COMMAND
            + " as the console user, repair read access, and retry verification"
        )
    return (
        f"screen saver will lock this Mac after {idle_seconds / 60:g} minutes; "
        "run " + SCREEN_SAVER_DISABLE_COMMAND + " as the console user and retry"
    )


def read_secure_keyboard_entry(run: RunRemote) -> bool:
    """Return whether Terminal is refusing synthetic keystrokes.

    An unset preference is the macOS default, which is off, so a read that
    finds nothing is a real answer rather than an unknown one.
    """
    result = run(
        f"/usr/bin/defaults read {SECURE_KEYBOARD_ENTRY_DOMAIN} "
        f"{SECURE_KEYBOARD_ENTRY_KEY}",
        timeout=10,
    )
    if result.returncode:
        return False
    return result.stdout.strip() in {"1", "true", "YES", "Yes"}


def _applescript_reachable(
    run: RunRemote,
    lines: list[str],
) -> tuple[bool, str]:
    result = run_osascript(run, lines)
    detail = (result.stderr or result.stdout or "").strip()
    return result.returncode == 0, detail[:200]


def system_events_reachable(run: RunRemote) -> tuple[bool, str]:
    """Return whether SSH-attributed AppleEvents reach System Events."""
    return _applescript_reachable(
        run,
        ['tell application "System Events" to count processes'],
    )


def terminal_app_reachable(run: RunRemote) -> tuple[bool, str]:
    """Return whether SSH-attributed AppleEvents reach Terminal."""
    return _applescript_reachable(
        run,
        ['tell application "Terminal" to count windows'],
    )


def probe_host_display_context(
    run: RunRemote, *, expected_console_user: str | None = None
) -> dict[str, Any]:
    """Read the host facts that decide whether any capture could have worked."""
    context = {
        "console_user": read_console_user(run),
        "display_locked": read_display_locked(run),
    }
    if context["display_locked"] is True:
        context["screen_sharing_active"] = read_screen_sharing_active(run)
        if (
            expected_console_user is None
            or context["console_user"] == expected_console_user
        ):
            context["screen_saver_idle_seconds"] = read_screen_saver_idle_seconds(
                run, context["console_user"]
            )
    return context


__all__ = [
    "SECURE_KEYBOARD_ENTRY_DOMAIN",
    "SECURE_KEYBOARD_ENTRY_KEY",
    "display_lock_recovery",
    "probe_host_display_context",
    "read_console_user",
    "read_display_locked",
    "read_load_average",
    "read_secure_keyboard_entry",
    "read_screen_sharing_active",
    "read_screen_saver_idle_seconds",
    "screen_saver_recovery",
    "system_events_reachable",
    "terminal_app_reachable",
]
