"""Drive a user-visible macOS Terminal.app session over SSH."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import shlex
import subprocess
import time

from yoke_harness.ssh_mac_terminal_timing import (
    BRIDGE_POLL_SECONDS,
    FOCUS_WAIT_BASE_SECONDS,
    load_scaled_wait,
)


RunRemote = Callable[..., subprocess.CompletedProcess[str]]


_KEY_CODES = {
    "Down": 125,
    "Enter": 36,
    "Escape": 53,
    "Space": 49,
    "Up": 126,
}
_CONTROL_KEY_CODES = {
    "C-c": 8,
    "C-j": 38,
    "C-u": 32,
}


def run_osascript(
    run: RunRemote, lines: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    """Execute one bounded AppleScript through the controlled Mac transport."""
    apple = "\n".join(lines)
    return run(
        "/usr/bin/osascript -e " + shlex.quote(apple),
        timeout=20,
    )


@dataclass(frozen=True)
class KeystrokeDelivery:
    """What happened when the bridge tried to type into one window.

    Focus and delivery are separate answers because their recoveries are:
    a window that never became frontmost means the keys would have gone
    somewhere else, while a focused window that refused them means macOS
    blocked the event.
    """

    focused: bool
    delivered: bool
    focus_wait_seconds: float
    frontmost_process: str | None = None


def wait_for_terminal_app_focus(
    run: RunRemote,
    *,
    window_id: int,
    timeout_seconds: float,
) -> tuple[bool, str | None]:
    """Wait until *window_id* is the frontmost window of the frontmost app.

    Activating Terminal and typing in the same breath is a race the busy host
    loses: `activate` returns as soon as the request is made, and on a loaded
    Mac the new window is not frontmost for seconds afterwards, so the
    keystrokes land in whatever window still is. Waiting for the window server
    to agree closes it, and the frontmost process name rides back so a failure
    names what held focus instead.
    """
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    frontmost: str | None = None
    while True:
        result = run_osascript(
            run,
            [
                'tell application "System Events"',
                "set frontApp to name of first application process "
                "whose frontmost is true",
                "end tell",
                'tell application "Terminal"',
                f'if not (exists window id {window_id}) then return "missing|0"',
                "set frontId to id of front window",
                "end tell",
                'return frontApp & "|" & (frontId as text)',
            ],
        )
        if result.returncode == 0:
            name, _separator, observed = result.stdout.strip().partition("|")
            frontmost = name or None
            if name == "Terminal" and observed.strip() == str(window_id):
                return True, frontmost
        if time.monotonic() >= deadline:
            return False, frontmost
        time.sleep(BRIDGE_POLL_SECONDS)


def set_terminal_app_window_bounds(
    run: RunRemote,
    *,
    window_id: int,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    """Un-minimize one window, request *bounds*, and report what it took."""
    left, top, right, bottom = bounds
    result = run_osascript(
        run,
        [
            'tell application "Terminal"',
            f'if not (exists window id {window_id}) then return ""',
            f"set targetWindow to window id {window_id}",
            "set miniaturized of targetWindow to false",
            f"set bounds of targetWindow to {{{left}, {top}, {right}, {bottom}}}",
            "set observed to bounds of targetWindow",
            'return ((item 1 of observed) as text) & "," & '
            '((item 2 of observed) as text) & "," & '
            '((item 3 of observed) as text) & "," & '
            "((item 4 of observed) as text)",
            "end tell",
        ],
    )
    if result.returncode:
        return None
    parts = result.stdout.strip().split(",")
    if len(parts) != 4:
        return None
    try:
        return tuple(int(float(part.strip())) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def open_terminal_app_window(
    run: RunRemote,
    *,
    command: str,
    terminal_size: tuple[int, int] | None = None,
    bounds: tuple[int, int, int, int] | None = None,
) -> int | None:
    """Start *command* in a new Terminal.app window, placed when told where.

    Callers that will capture the window pass bounds derived from the live
    display; a window opened without them keeps whatever frame Terminal
    restored, which is only safe when nothing reads its pixels.
    """
    lines = [
        'tell application "Terminal"',
        "activate",
        'set targetTab to do script ""',
        "set targetWindow to front window",
    ]
    if terminal_size is not None:
        lines.extend(
            [
                f"set number of columns of targetWindow to {terminal_size[0]}",
                f"set number of rows of targetWindow to {terminal_size[1]}",
            ]
        )
    lines.extend(
        [
            "delay 0.5",
            f"do script {json.dumps(command)} in targetTab",
            "return id of targetWindow",
            "end tell",
        ]
    )
    result = run_osascript(run, lines)
    try:
        window_id = int(result.stdout.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    if result.returncode or window_id <= 0:
        return None
    if bounds is not None:
        set_terminal_app_window_bounds(run, window_id=window_id, bounds=bounds)
    return window_id


def close_terminal_app_window(
    run: RunRemote,
    *,
    window_id: int | None,
) -> None:
    """Best-effort cleanup for one Terminal.app window."""
    if window_id is None:
        return
    run_osascript(
        run,
        [
            'tell application "Terminal"',
            f"if exists window id {window_id} then",
            f"close window id {window_id}",
            "end if",
            "end tell",
        ],
    )


def capture_terminal_app_transcript(
    run: RunRemote,
    *,
    window_id: int,
) -> str:
    """Read the visible Terminal.app tab contents without changing its TTY."""
    result = run_osascript(
        run,
        [
            'tell application "Terminal"',
            f'if not (exists window id {window_id}) then return ""',
            f"set targetWindow to window id {window_id}",
            "return contents of selected tab of targetWindow",
            "end tell",
        ],
    )
    return result.stdout.replace("\x00", "") if result.returncode == 0 else ""


def send_terminal_app_keys(
    run: RunRemote,
    *,
    window_id: int,
    keys: Sequence[str],
    load_average: float | None = None,
) -> KeystrokeDelivery:
    """Focus one Terminal.app window and deliver native macOS key events.

    The focus wait scales with the host's load, because the delay between
    asking for focus and holding it is exactly what the load makes longer.
    """
    focus_wait = load_scaled_wait(FOCUS_WAIT_BASE_SECONDS, load_average)
    raise_window = run_osascript(
        run,
        [
            'tell application "Terminal"',
            f'if not (exists window id {window_id}) then return "false"',
            f"set targetWindow to window id {window_id}",
            "set miniaturized of targetWindow to false",
            "set index of targetWindow to 1",
            "activate",
            "end tell",
            'return "true"',
        ],
    )
    if raise_window.returncode or raise_window.stdout.strip().casefold() != "true":
        return KeystrokeDelivery(
            focused=False,
            delivered=False,
            focus_wait_seconds=focus_wait,
        )
    focused, frontmost = wait_for_terminal_app_focus(
        run,
        window_id=window_id,
        timeout_seconds=focus_wait,
    )
    if not focused:
        return KeystrokeDelivery(
            focused=False,
            delivered=False,
            focus_wait_seconds=focus_wait,
            frontmost_process=frontmost,
        )
    lines = [
        'tell application "System Events"',
    ]
    for index, key in enumerate(keys):
        if key.startswith("paste_file:"):
            path = key.removeprefix("paste_file:")
            if not path.startswith("/"):
                return KeystrokeDelivery(
                    focused=True,
                    delivered=False,
                    focus_wait_seconds=focus_wait,
                    frontmost_process=frontmost,
                )
            lines.extend(
                [
                    "set pasteText to do shell script "
                    + json.dumps("/bin/cat " + shlex.quote(path)),
                    "keystroke pasteText",
                ]
            )
        elif key in _KEY_CODES:
            lines.append(f"key code {_KEY_CODES[key]}")
        elif key in _CONTROL_KEY_CODES:
            lines.append(f"key code {_CONTROL_KEY_CODES[key]} using {{control down}}")
        else:
            lines.append(f"keystroke {json.dumps(key)}")
        if index + 1 < len(keys):
            lines.append("delay 0.2")
    lines.extend(["end tell", 'return "true"'])
    result = run_osascript(run, lines)
    return KeystrokeDelivery(
        focused=True,
        delivered=(
            result.returncode == 0 and result.stdout.strip().casefold() == "true"
        ),
        focus_wait_seconds=focus_wait,
        frontmost_process=frontmost,
    )


__all__ = [
    "KeystrokeDelivery",
    "RunRemote",
    "capture_terminal_app_transcript",
    "close_terminal_app_window",
    "open_terminal_app_window",
    "run_osascript",
    "set_terminal_app_window_bounds",
    "send_terminal_app_keys",
    "wait_for_terminal_app_focus",
]
