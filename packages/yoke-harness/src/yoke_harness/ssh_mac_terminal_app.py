"""Drive a user-visible macOS Terminal.app session over SSH."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
import json
from pathlib import Path
import shlex
import subprocess
import time
from uuid import uuid4


RunRemote = Callable[..., subprocess.CompletedProcess[str]]
TERMINAL_WINDOW_BOUNDS = (66, 90, 1566, 820)
_HELPER_WINDOW_BOUNDS = (40, 850, 1540, 900)
_CAPTURE_TIMEOUT_SECONDS = 10
_CAPTURE_POLL_SECONDS = 0.1
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


def open_terminal_app_window(
    run: RunRemote,
    *,
    command: str,
    terminal_size: tuple[int, int] | None = None,
) -> int | None:
    """Start *command* in a new, fully sized Terminal.app window."""
    left, top, right, bottom = TERMINAL_WINDOW_BOUNDS
    lines = [
        'tell application "Terminal"',
        "activate",
        'set targetTab to do script ""',
        "set targetWindow to front window",
        f"set bounds of targetWindow to {{{left}, {top}, {right}, {bottom}}}",
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
    return window_id if result.returncode == 0 and window_id > 0 else None


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


def _terminal_app_screenshot_payload(
    run: RunRemote,
    *,
    remote: str,
    window_id: int,
) -> str | None:
    """Capture the target's region through Terminal.app's recording grant."""
    helper_bounds = ", ".join(str(value) for value in _HELPER_WINDOW_BOUNDS)
    result = run_osascript(
        run,
        [
            'tell application "Terminal"',
            f"if not (exists window id {window_id}) then return 0",
            f"set targetWindow to window id {window_id}",
            "set b to bounds of targetWindow",
            "set leftPos to item 1 of b",
            "set topPos to item 2 of b",
            "set widthVal to (item 3 of b) - leftPos",
            "set heightVal to (item 4 of b) - topPos",
            (
                'set shotCmd to "/bin/sleep 0.5; '
                '/usr/sbin/screencapture -x -R" & leftPos & "," & topPos & '
                '"," & widthVal & "," & heightVal & " -o " & '
                f"quoted form of {json.dumps(remote)}"
            ),
            "do script shotCmd",
            "set helperWindow to front window",
            f"set bounds of helperWindow to {{{helper_bounds}}}",
            "set index of targetWindow to 1",
            "activate",
            "return id of helperWindow",
            "end tell",
        ],
    )
    try:
        helper_id = int(result.stdout.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    if result.returncode or helper_id <= 0:
        return None
    try:
        deadline = time.monotonic() + _CAPTURE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            encoded = run(
                f"/bin/test -s {shlex.quote(remote)} && "
                f"/usr/bin/base64 < {shlex.quote(remote)}",
                timeout=10,
            )
            if encoded.returncode == 0 and encoded.stdout.strip():
                return encoded.stdout
            time.sleep(_CAPTURE_POLL_SECONDS)
        return None
    finally:
        close_terminal_app_window(run, window_id=helper_id)


def capture_terminal_app_screen(
    run: RunRemote,
    *,
    session: str,
    key: str,
    evidence_root: Path,
    window_id: int,
) -> Path | None:
    """Retain one screenshot of the exact user-visible Terminal.app region."""
    remote = f"/tmp/{session}-{key}.png"
    try:
        encoded = _terminal_app_screenshot_payload(
            run,
            remote=remote,
            window_id=window_id,
        )
        if encoded is None:
            return None
        try:
            payload = base64.b64decode(encoded)
        except ValueError:
            return None
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
    path = evidence_root / f"{key}.png"
    path.write_bytes(payload)
    return path


def verify_terminal_app_control(
    run: RunRemote,
) -> tuple[bool, dict[str, bool], str | None]:
    """Exercise direct launch, native input, transcript, and region capture."""
    identity = uuid4().hex[:12]
    session = f"yoke-terminal-app-{identity}"
    remote = f"/tmp/{session}.png"
    received = f"received-{identity}"
    command = (
        "printf 'terminal-app-ready\\n'; "
        "IFS= read -r value; printf 'received-%s\\n' \"$value\"; sleep 15"
    )
    checks = {
        "terminal_app_launch": False,
        "terminal_app_input": False,
        "terminal_app_transcript": False,
        "terminal_app_screenshot": False,
    }
    window_id = open_terminal_app_window(run, command=command)
    try:
        if window_id is None:
            return False, checks, "terminal_app_control_unavailable"
        checks["terminal_app_launch"] = True
        ready = False
        ready_deadline = time.monotonic() + 5
        while time.monotonic() < ready_deadline:
            transcript = capture_terminal_app_transcript(
                run,
                window_id=window_id,
            )
            if "terminal-app-ready" in transcript:
                ready = True
                break
            time.sleep(0.1)
        if ready:
            checks["terminal_app_input"] = send_terminal_app_keys(
                run,
                window_id=window_id,
                keys=(identity, "Enter"),
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                transcript = capture_terminal_app_transcript(
                    run,
                    window_id=window_id,
                )
                if received in transcript:
                    checks["terminal_app_transcript"] = True
                    break
                time.sleep(0.1)
        checks["terminal_app_screenshot"] = (
            _terminal_app_screenshot_payload(
                run,
                remote=remote,
                window_id=window_id,
            )
            is not None
        )
        ok = all(checks.values())
        return ok, checks, None if ok else "terminal_app_control_unavailable"
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
        if window_id is not None:
            send_terminal_app_keys(
                run,
                window_id=window_id,
                keys=("C-c",),
            )
        close_terminal_app_window(run, window_id=window_id)


__all__ = [
    "RunRemote",
    "TERMINAL_WINDOW_BOUNDS",
    "capture_terminal_app_screen",
    "capture_terminal_app_transcript",
    "close_terminal_app_window",
    "open_terminal_app_window",
    "run_osascript",
    "send_terminal_app_keys",
    "verify_terminal_app_control",
]
