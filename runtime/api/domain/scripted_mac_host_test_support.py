"""A scripted macOS host that answers the probes Terminal.app control sends."""

from __future__ import annotations

import base64
import subprocess
from typing import Any

from runtime.api.domain.terminal_display_probe_test_support import (
    DISPLAY_FRAME_PROBE_MARKER,
    display_frame_stdout,
)


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
    ) -> None:
        self.visible_frame = visible_frame
        self.display = display
        self.capture_origin = capture_origin
        self.display_count = display_count
        self.backing_scale = backing_scale
        self.frame_available = frame_available
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
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=self._stdout(command),
            stderr="",
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
        answer = self.reply(command)
        return "" if answer is None else answer

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


__all__ = ["ScriptedMacHost"]
