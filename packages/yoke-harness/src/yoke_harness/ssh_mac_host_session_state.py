"""Read the host facts that decide whether the GUI bridge can work at all.

Each fact is read on its own and answers `True`, `False`, or `None` — the last
meaning the probe itself did not answer. Collapsing "not locked" into "could
not tell whether it is locked" is what turns a diagnosis into a guess, and the
recoveries differ: one sends a person to the screen, the other to the probe.
"""

from __future__ import annotations

from typing import Any

from yoke_harness.ssh_mac_terminal_app import RunRemote, run_osascript


#: Terminal's own setting. While it is on, macOS refuses every synthetic
#: keystroke sent to Terminal, silently, so the window sits at its prompt while
#: the bridge reports the keys as delivered.
SECURE_KEYBOARD_ENTRY_DOMAIN = "com.apple.Terminal"
SECURE_KEYBOARD_ENTRY_KEY = "SecureKeyboardEntry"


def read_console_user(run: RunRemote) -> str | None:
    """Return the login that owns the host's graphical session."""
    result = run("/usr/bin/stat -f%Su /dev/console", timeout=10)
    return result.stdout.strip() if result.returncode == 0 else None


def read_display_locked(run: RunRemote) -> bool | None:
    """Return whether the host's screen is locked."""
    result = run(
        "/usr/sbin/ioreg -n Root -d1 -k CGSSessionScreenIsLocked",
        timeout=10,
    )
    if result.returncode:
        return None
    return '"CGSSessionScreenIsLocked" = Yes' in result.stdout


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


def probe_host_display_context(run: RunRemote) -> dict[str, Any]:
    """Read the host facts that decide whether any capture could have worked."""
    return {
        "console_user": read_console_user(run),
        "display_locked": read_display_locked(run),
    }


__all__ = [
    "SECURE_KEYBOARD_ENTRY_DOMAIN",
    "SECURE_KEYBOARD_ENTRY_KEY",
    "probe_host_display_context",
    "read_console_user",
    "read_display_locked",
    "read_load_average",
    "read_secure_keyboard_entry",
    "system_events_reachable",
    "terminal_app_reachable",
]
