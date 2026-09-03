"""A scripted macOS host that answers the probes Terminal.app control sends."""

from __future__ import annotations

import base64
import subprocess
from typing import Any

from runtime.api.domain.terminal_display_probe_test_support import (
    DISPLAY_FRAME_PROBE_MARKER,
    display_frame_stdout,
)

#: Distinctive fragments of the AppleScript and shell probes the bridge sends.
FOCUS_PROBE_MARKER = "set frontApp to name of first application process"
RAISE_WINDOW_MARKER = "set index of targetWindow to 1"
LOAD_AVERAGE_COMMAND = "/usr/sbin/sysctl -n vm.loadavg"
SECURE_KEYBOARD_ENTRY_COMMAND = "/usr/bin/defaults read com.apple.Terminal"
REACHABILITY_PROBES = {
    "system_events": 'tell application "System Events" to count processes',
    "terminal": 'tell application "Terminal" to count windows',
}


class ScriptedMacHost:
    """Answer window opens, placements, and GUI-session command round trips.

    Subclasses handle whatever else their subject sends by overriding `reply`,
    and shape placement by overriding `place`.
    """

    def __init__(
        self,
        *,
        visible_frame: tuple[int, int, int, int] = (0, 25, 1920, 975),
        display: tuple[int, int] = (1920, 1080),
        capture_origin: tuple[int, int] = (0, 0),
        display_count: int = 1,
        backing_scale: float = 1.0,
        frame_available: bool = True,
        first_window_id: int = 441,
        frontmost_process: str = "Terminal",
        focus_window_id: int | None = None,
        load_average: float = 0.5,
        secure_keyboard_entry: bool = False,
        system_events_reachable: bool = True,
        terminal_app_reachable: bool = True,
    ) -> None:
        self.visible_frame = visible_frame
        self.display = display
        self.capture_origin = capture_origin
        self.display_count = display_count
        self.backing_scale = backing_scale
        self.frame_available = frame_available
        self.frontmost_process = frontmost_process
        self.focus_window_id = focus_window_id
        self.load_average = load_average
        self.secure_keyboard_entry = secure_keyboard_entry
        self.system_events_reachable = system_events_reachable
        self.terminal_app_reachable = terminal_app_reachable
        self.commands: list[str] = []
        self.window_ids: list[int] = []
        self.requested_bounds: list[tuple[int, int, int, int]] = []
        self.placed_bounds: list[tuple[int, int, int, int]] = []
        self._next_window_id = first_window_id
        self._placement_attempts: dict[int, int] = {}
        self._pending_frame_probe = False

    def __call__(
        self,
        command: str,
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if REACHABILITY_PROBES["system_events"] in command:
            return self._reachability(command, self.system_events_reachable, "-1743")
        if REACHABILITY_PROBES["terminal"] in command:
            return self._reachability(command, self.terminal_app_reachable, "-1743")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=self._stdout(command),
            stderr="",
        )

    @staticmethod
    def _reachability(
        command: str,
        reachable: bool,
        error_number: str,
    ) -> subprocess.CompletedProcess[str]:
        if reachable:
            return subprocess.CompletedProcess(command, 0, stdout="2\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=(
                f"execution error: Not authorized to send Apple events ({error_number})"
            ),
        )

    # --- overridable ----------------------------------------------------
    def reply(self, command: str) -> str | None:
        """Answer a command this host does not handle itself."""
        return None

    def place(
        self,
        requested: tuple[int, int, int, int],
        attempt: int,
    ) -> tuple[int, int, int, int]:
        """Report the bounds the window manager actually gave the window."""
        return requested

    # --- scripted answers ------------------------------------------------
    def _stdout(self, command: str) -> str:
        if "set targetTab to do script" in command:
            self._next_window_id += 1
            self.window_ids.append(self._next_window_id)
            self._pending_frame_probe = DISPLAY_FRAME_PROBE_MARKER in command
            return str(self._next_window_id)
        if "set bounds of targetWindow to {" in command:
            return self._place(command)
        if command.startswith("if /bin/test -f "):
            return (
                "0\n"
                if self.frame_available or not self._pending_frame_probe
                else "1\n"
            )
        if command.startswith("/usr/bin/base64 < "):
            return self._gui_session_output(command)
        if FOCUS_PROBE_MARKER in command:
            return self._focus_answer(command)
        if RAISE_WINDOW_MARKER in command and "set bounds" not in command:
            return "true"
        if command == LOAD_AVERAGE_COMMAND:
            return f"{{ {self.load_average:.2f} 0.40 0.30 }}"
        if command.startswith(SECURE_KEYBOARD_ENTRY_COMMAND):
            return "1" if self.secure_keyboard_entry else "0"
        answer = self.reply(command)
        return "" if answer is None else answer

    def _focus_answer(self, command: str) -> str:
        """Report which application and window the window server has in front.

        By default the window the poll asks about is the one in front, which is
        what a responsive host does. A test models a host that will not give
        focus up by pinning `frontmost_process` or `focus_window_id`.
        """
        window_id = self.focus_window_id
        if window_id is None:
            window_id = int(command.split("exists window id ")[1].split(")")[0].strip())
        return f"{self.frontmost_process}|{window_id}"

    def _gui_session_output(self, command: str) -> str:
        if not self._pending_frame_probe:
            return ""
        if command.endswith(".stdout"):
            if not self.frame_available:
                return ""
            return _encode(
                display_frame_stdout(
                    visible_frame=self.visible_frame,
                    display=self.display,
                    capture_origin=self.capture_origin,
                    display_count=self.display_count,
                    backing_scale=self.backing_scale,
                )
            )
        if command.endswith(".stderr"):
            if self.frame_available:
                return ""
            return _encode("execution error: no display is attached")
        return ""

    def _place(self, command: str) -> str:
        window_id = int(
            command.split("set targetWindow to window id ")[1].split("\n")[0].strip()
        )
        raw = command.split("set bounds of targetWindow to {")[1].split("}")[0]
        requested = tuple(int(part.strip()) for part in raw.split(","))
        self.requested_bounds.append(requested)  # type: ignore[arg-type]
        attempt = self._placement_attempts.get(window_id, 0)
        self._placement_attempts[window_id] = attempt + 1
        placed = self.place(requested, attempt)  # type: ignore[arg-type]
        self.placed_bounds.append(placed)
        return ",".join(str(value) for value in placed)

    # --- assertions helpers ----------------------------------------------
    def crop_rectangles(self) -> list[tuple[int, int, int, int]]:
        """Every window rectangle a capture command actually cropped to."""
        rectangles = []
        for command in self.commands:
            if "--cropOffset" not in command:
                continue
            parts = command.split("sips -c ")[1].split()
            height, width = int(parts[0]), int(parts[1])
            top, left = int(parts[3]), int(parts[4])
            rectangles.append((left, top, left + width, top + height))
        return rectangles


def _encode(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


__all__ = [
    "FOCUS_PROBE_MARKER",
    "LOAD_AVERAGE_COMMAND",
    "REACHABILITY_PROBES",
    "RAISE_WINDOW_MARKER",
    "SECURE_KEYBOARD_ENTRY_COMMAND",
    "ScriptedMacHost",
]
