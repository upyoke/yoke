"""Close one driven Terminal.app window and prove it is gone."""

from __future__ import annotations

from yoke_harness.ssh_mac_terminal_app import RunRemote, run_osascript


def close_terminal_app_window(
    run: RunRemote,
    *,
    window_id: int | None,
) -> bool:
    """Force-close one Terminal.app window and return whether it is gone.

    A plain close of a still-running window (osascript blocked on consent)
    leaves a "terminate running processes" sheet up, so its ttys are killed
    first. The tty paths are read inside the Terminal block and killed outside
    it: a tab reference does not coerce to text, and an error there used to
    abort the script before the close, leaving one window behind per command.
    Terminal hides a closed window at once and releases it a little later, so
    a window that still exists but is no longer visible counts as closed.
    """
    if window_id is None:
        return True
    result = run_osascript(
        run,
        [
            'tell application "Terminal"',
            f'if not (exists window id {window_id}) then return "closed"',
            f"set ttyPaths to tty of every tab of window id {window_id}",
            "end tell",
            "repeat with ttyPath in ttyPaths",
            'do shell script "/usr/bin/pkill -KILL -t " & quoted form of '
            '(text 6 thru -1 of (ttyPath as text)) & " || true"',
            "end repeat",
            "delay 0.5",
            'tell application "Terminal"',
            f"if exists window id {window_id} then close window id {window_id}",
            f"if exists window id {window_id} then",
            f'if visible of window id {window_id} then return "open"',
            "end if",
            "end tell",
            'return "closed"',
        ],
    )
    return result.returncode == 0 and result.stdout.strip() == "closed"


__all__ = ["close_terminal_app_window"]
