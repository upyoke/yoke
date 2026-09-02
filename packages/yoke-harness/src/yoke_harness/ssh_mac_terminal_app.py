"""Drive a user-visible macOS Terminal.app session over SSH."""

from __future__ import annotations

from collections.abc import Sequence
import json
import shlex
import subprocess

from yoke_harness.ssh_mac_display_frame import (
    DisplayFrame,
    RunRemote,
    resolve_display_frame,
    window_layout,
)


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


def place_terminal_app_window(
    run: RunRemote,
    *,
    window_id: int,
    frame: DisplayFrame,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    """Move one window onto *frame* and report the bounds it actually took.

    Terminal restores a saved frame for every new window and clamps requested
    sizes to whole character cells, so the requested rectangle is a proposal.
    This reads the result back and re-anchors once when the window landed
    outside the display, which is what defeats a region capture.
    """
    observed = _set_window_bounds(run, window_id=window_id, bounds=bounds)
    if observed is None or frame.contains(observed):
        return observed
    return _set_window_bounds(
        run,
        window_id=window_id,
        bounds=frame.anchored(observed),
    )


def _set_window_bounds(
    run: RunRemote,
    *,
    window_id: int,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
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
    display_frame: DisplayFrame | None = None,
    bounds: tuple[int, int, int, int] | None = None,
) -> int | None:
    """Start *command* in a new Terminal.app window placed on the display.

    Placement is derived from the display's own visible frame rather than
    fixed coordinates, because a restored off-screen frame, a different
    display size, or a screen-shared session all move where those
    coordinates land.
    """
    frame = display_frame or resolve_display_frame(run)
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
    place_terminal_app_window(
        run,
        window_id=window_id,
        frame=frame,
        bounds=bounds if bounds is not None else window_layout(frame).target,
    )
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
) -> bool:
    """Focus one Terminal.app window and deliver native macOS key events."""
    lines = [
        'tell application "Terminal"',
        f"if not (exists window id {window_id}) then return false",
        f"set targetWindow to window id {window_id}",
        "set index of targetWindow to 1",
        "activate",
        "end tell",
        "delay 0.1",
        'tell application "System Events"',
    ]
    for index, key in enumerate(keys):
        if key.startswith("paste_file:"):
            path = key.removeprefix("paste_file:")
            if not path.startswith("/"):
                return False
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
    lines.extend(["end tell", "return true"])
    result = run_osascript(run, lines)
    return result.returncode == 0 and result.stdout.strip().casefold() == "true"


__all__ = [
    "RunRemote",
    "capture_terminal_app_transcript",
    "close_terminal_app_window",
    "open_terminal_app_window",
    "place_terminal_app_window",
    "run_osascript",
    "send_terminal_app_keys",
]
