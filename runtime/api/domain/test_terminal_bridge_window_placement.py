"""Terminal.app bridge window placement, capture, and named failure classes."""

from __future__ import annotations

from collections.abc import Callable
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_execution import (
    TERMINAL_CAPTURE_RECOVERY,
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE,
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE,
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
    TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE,
)
from runtime.api.domain.terminal_display_probe_test_support import (
    DISPLAY_FRAME_PROBE_PREFIX,
    display_frame_stdout,
)
from yoke_harness import ssh_mac_terminal_bridge_check
from yoke_harness.ssh_mac_display_frame import DisplayFrame, window_layout
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl


Placement = Callable[[tuple[int, int, int, int], int], tuple[int, int, int, int]]
_IDENTITY = "b" * 12


class FakeMac:
    """A scripted Terminal.app host: placement, transcripts, and captures."""

    def __init__(
        self,
        *,
        visible_frame: tuple[int, int, int, int] = (0, 25, 1920, 975),
        display: tuple[int, int] = (1920, 1080),
        placement: Placement | None = None,
        captures: tuple[str, ...] = ("cG5nLW9uZQ==", "cG5nLXR3bw=="),
        console_user: str = "yoke-test",
        locked: bool = False,
        input_ok: bool = True,
        frame_available: bool = True,
    ) -> None:
        self.visible_frame = visible_frame
        self.display = display
        self.placement = placement or (lambda requested, _attempt: requested)
        self.captures = list(captures)
        self.console_user = console_user
        self.locked = locked
        self.input_ok = input_ok
        self.frame_available = frame_available
        self.commands: list[str] = []
        self.requested_bounds: list[tuple[int, int, int, int]] = []
        self.placed_bounds: list[tuple[int, int, int, int]] = []
        self._transcript_reads = 0
        self._next_window_id = 440
        self._placement_attempts: dict[int, int] = {}
        self._last_window_id = 0

    def __call__(
        self,
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=self._stdout(command),
            stderr="",
        )

    def _stdout(self, command: str) -> str:
        if command.startswith(DISPLAY_FRAME_PROBE_PREFIX):
            if not self.frame_available:
                raise _NonZero()
            return display_frame_stdout(
                visible_frame=self.visible_frame,
                display=self.display,
            )
        if "set targetTab to do script" in command:
            self._next_window_id += 1
            self._last_window_id = self._next_window_id
            return str(self._next_window_id)
        if "set bounds of targetWindow to {" in command:
            return self._place(command)
        if "return contents of selected tab" in command:
            self._transcript_reads += 1
            if self._transcript_reads == 1 or not self.input_ok:
                return "terminal-app-ready\n"
            return f"received-{_IDENTITY}\n"
        if 'tell application "System Events"' in command:
            return "true" if self.input_ok else "false"
        if command.startswith("if /bin/test -f "):
            return "0"
        if command.startswith("/bin/test -s "):
            return self.captures.pop(0) if self.captures else ""
        if command == "/usr/bin/stat -f%Su /dev/console":
            return self.console_user
        if command.startswith("/usr/sbin/ioreg"):
            return (
                '    | |   "CGSSessionScreenIsLocked" = Yes'
                if self.locked
                else '    | |   "kCGSSessionOnConsoleKey" = Yes'
            )
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
        placed = self.placement(requested, attempt)  # type: ignore[arg-type]
        self.placed_bounds.append(placed)
        return ",".join(str(value) for value in placed)

    def capture_rectangles(self) -> list[tuple[int, int, int, int]]:
        """Every region rectangle a capture command actually asked for."""
        rectangles = []
        for command in self.commands:
            if "screencapture" not in command or " -R " not in command:
                continue
            rect = command.split(" -R ")[1].split(" ")[0]
            left, top, width, height = (int(value) for value in rect.split(","))
            rectangles.append((left, top, left + width, top + height))
        return rectangles


class _NonZero(Exception):
    """Raised inside the fake to model a failing remote command."""


def _run(mac: FakeMac) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        try:
            return mac(command, **kwargs)
        except _NonZero:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="execution error: no display",
            )

    return run


def _check(mac: FakeMac, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ssh_mac_terminal_bridge_check,
        "uuid4",
        lambda: SimpleNamespace(hex="b" * 32),
    )
    control = SshMacHostControl.__new__(SshMacHostControl)
    control._run = _run(mac)
    control._user = "yoke-test"
    return control.check_terminal_bridge()


def test_bridge_places_both_windows_inside_a_small_visible_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A display the previous fixed rectangle (66, 90, 1566, 820) does not fit.
    frame = DisplayFrame(
        left=0,
        top=25,
        width=1280,
        height=700,
        display_width=1280,
        display_height=800,
    )
    mac = FakeMac(visible_frame=(0, 25, 1280, 700), display=(1280, 800))

    result = _check(mac, monkeypatch)

    assert result.ok is True
    assert result.error_code is None
    assert mac.requested_bounds, "the bridge never placed a window"
    for bounds in mac.requested_bounds:
        assert frame.contains(bounds), bounds
    layout = window_layout(frame)
    # The helper that issues the capture stays clear of the captured region.
    assert layout.helper[1] >= layout.target[3]
    assert mac.capture_rectangles() == [layout.target, layout.target]


def test_bridge_recovers_a_window_terminal_restored_off_the_left_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    off_screen = (-1400, 90, 100, 820)

    def placement(
        requested: tuple[int, int, int, int],
        attempt: int,
    ) -> tuple[int, int, int, int]:
        return off_screen if attempt == 0 else requested

    mac = FakeMac(placement=placement)

    result = _check(mac, monkeypatch)

    assert result.ok is True
    assert result.error_code is None
    frame = DisplayFrame(
        left=0,
        top=25,
        width=1920,
        height=975,
        display_width=1920,
        display_height=1080,
    )
    assert off_screen in mac.placed_bounds
    for rectangle in mac.capture_rectangles():
        assert frame.contains(rectangle), rectangle


def test_bridge_names_a_window_that_will_not_come_on_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(placement=lambda _requested, _attempt: (-1400, 90, 100, 820))

    result = _check(mac, monkeypatch)

    assert result.ok is False
    assert result.error_code == TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE
    diagnostics = result.evidence["capture_diagnostics"]
    assert diagnostics["window_bounds"] == [-1400, 90, 100, 820]
    assert diagnostics["display_visible_frame"] == [0, 25, 1920, 1000]
    assert diagnostics["display_size"] == [1920, 1080]
    assert diagnostics["recovery"] == (
        TERMINAL_CAPTURE_RECOVERY[TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE]
    )
    assert mac.capture_rectangles() == []


def test_bridge_records_capture_diagnostics_when_frames_never_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(captures=("c2FtZQ==", "c2FtZQ=="))

    result = _check(mac, monkeypatch)

    assert result.ok is False
    assert result.error_code == TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE
    diagnostics = result.evidence["capture_diagnostics"]
    assert "screencapture" in diagnostics["command"]
    assert diagnostics["exit_code"] == 0
    assert diagnostics["stderr"] == ""
    assert diagnostics["console_user"] == "yoke-test"
    assert diagnostics["display_locked"] is False
    assert diagnostics["frames_differed"] is False
    assert diagnostics["recovery"] == (
        TERMINAL_CAPTURE_RECOVERY[TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE]
    )


def test_bridge_names_a_console_user_that_does_not_own_the_window_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(captures=("c2FtZQ==", "c2FtZQ=="), console_user="root")

    result = _check(mac, monkeypatch)

    assert result.error_code == TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE
    assert result.evidence["capture_diagnostics"]["console_user"] == "root"


def test_bridge_names_a_locked_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(captures=("c2FtZQ==", "c2FtZQ=="), locked=True)

    result = _check(mac, monkeypatch)

    assert result.error_code == TERMINAL_DISPLAY_LOCKED_ERROR_CODE
    assert result.evidence["capture_diagnostics"]["display_locked"] is True


def test_bridge_names_a_host_that_reports_no_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(frame_available=False)

    result = _check(mac, monkeypatch)

    assert result.ok is False
    assert result.error_code == TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE
    diagnostics = result.evidence["capture_diagnostics"]
    assert "no display" in diagnostics["error_detail"]
    assert diagnostics["recovery"] == (
        TERMINAL_CAPTURE_RECOVERY[TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE]
    )
    assert result.evidence["terminal_app_launch"] is False


def test_bridge_reports_generic_failure_without_input_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(input_ok=False)
    clock = {"now": 0.0}

    def advance(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(
        ssh_mac_terminal_bridge_check.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(ssh_mac_terminal_bridge_check.time, "sleep", advance)

    result = _check(mac, monkeypatch)

    assert result.ok is False
    assert result.error_code == (
        ssh_mac_terminal_bridge_check.TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE
    )
    assert result.evidence["terminal_app_input"] is False
    assert result.evidence["terminal_app_screenshot"] is False
