"""A minimal no-wrap terminal for replaying the setup wizard's output.

Textual paints with absolute cursor moves, newlines, styling, and private-mode
sequences, with line wrap disabled. The model honours exactly what affects
which characters are visible: cursor position, erase, newline scrolling at the
bottom row, and right-edge clipping. Resizing crops or extends the grid from
the top-left corner, as a terminal window does to the frame it is showing.
"""

from __future__ import annotations

import re

from textual.drivers.headless_driver import HeadlessDriver

_SEQUENCE = re.compile(
    r"\x1b\[(?P<private>[?>=<]?)(?P<params>[0-9;:]*)[ -/]*(?P<final>[@-~])"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[^\[\]]"
)


class TerminalModel:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.grid = [[" "] * width for _ in range(height)]
        self.row = 0
        self.col = 0
        self._pending_escape = ""

    @property
    def rows(self) -> list[str]:
        return ["".join(cells).rstrip() for cells in self.grid]

    @property
    def text(self) -> str:
        return "\n".join(self.rows)

    def resize(self, width: int, height: int) -> None:
        self.grid = [
            (cells[:width] + [" "] * max(0, width - len(cells)))
            for cells in self.grid[:height]
        ] + [[" "] * width for _ in range(max(0, height - len(self.grid)))]
        self.width, self.height = width, height
        self.row = min(self.row, height - 1)
        self.col = min(self.col, width - 1)

    def feed(self, data: str) -> None:
        data = self._pending_escape + data
        self._pending_escape = ""
        position = 0
        while (escape := data.find("\x1b", position)) != -1:
            self._write_text(data[position:escape])
            match = _SEQUENCE.match(data, escape)
            if match is None:
                # Driver writes are stream chunks, not complete frames. Textual
                # splits Windows frames at 8192 characters, even inside CSI/OSC.
                self._pending_escape = data[escape:]
                return
            if match.group("final") and not match.group("private"):
                self._control(match.group("final"), match.group("params"))
            position = match.end()
        self._write_text(data[position:])

    def _control(self, final: str, params: str) -> None:
        values = [int(value) if value else 0 for value in params.split(";")]
        if final == "H":
            row = values[0] if values[0] else 1
            col = values[1] if len(values) > 1 and values[1] else 1
            self.row = min(row, self.height) - 1
            self.col = min(col, self.width) - 1
        elif final == "J" and values[0] == 2:
            self.grid = [[" "] * self.width for _ in range(self.height)]
        elif final == "J" and values[0] == 0:
            self.grid[self.row][self.col :] = [" "] * (self.width - self.col)
            for row in range(self.row + 1, self.height):
                self.grid[row] = [" "] * self.width

    def _write_text(self, text: str) -> None:
        for char in text:
            if char == "\n":
                if self.row == self.height - 1:
                    self.grid = self.grid[1:] + [[" "] * self.width]
                else:
                    self.row += 1
            elif char == "\r":
                self.col = 0
            elif char >= " ":
                if self.col < self.width:
                    self.grid[self.row][self.col] = char
                    self.col += 1


def terminal_driver(terminal: TerminalModel) -> type[HeadlessDriver]:
    """A Textual driver that paints real frames into ``terminal``."""

    class TerminalModelDriver(HeadlessDriver):
        @property
        def is_headless(self) -> bool:
            return False

        def write(self, data: str) -> None:
            terminal.feed(data)

    return TerminalModelDriver


def expected_screen(app) -> TerminalModel:
    """What Textual believes is on screen, painted into a fresh terminal."""
    width, height = app.size
    expected = TerminalModel(width, height)
    frame = app.screen._compositor.render_full_update()
    expected.feed(frame.render_segments(app.console))
    return expected
