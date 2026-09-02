"""Terminal.app bridge window placement, capture, and named failure classes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.domain.scripted_mac_host_test_support import ScriptedMacHost
from yoke_contracts.machine_qa_execution import (
    TERMINAL_CAPTURE_RECOVERY,
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE,
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE,
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
    TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE,
)
from yoke_harness import ssh_mac_terminal_bridge_check
from yoke_harness.ssh_mac_display_frame import DisplayFrame, window_layout
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl


_IDENTITY = "b" * 12
_STANDARD_FRAME = DisplayFrame(
    left=0,
    top=25,
    width=1920,
    height=975,
    display_width=1920,
    display_height=1080,
    display_count=1,
)


class FakeMac(ScriptedMacHost):
    """A host that also answers the transcript, keystroke, and capture probes."""

    def __init__(
        self,
        *,
        captures: tuple[str, ...] = ("cG5nLW9uZQ==", "cG5nLXR3bw=="),
        console_user: str = "yoke-test",
        locked: bool = False,
        input_ok: bool = True,
        placement=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.captures = list(captures)
        self.console_user = console_user
        self.locked = locked
        self.input_ok = input_ok
        self._placement = placement
        self._transcript_reads = 0

    def place(self, requested, attempt):
        if self._placement is None:
            return requested
        return self._placement(requested, attempt)

    def reply(self, command: str) -> str | None:
        if "return contents of selected tab" in command:
            self._transcript_reads += 1
            if self._transcript_reads == 1 or not self.input_ok:
                return "terminal-app-ready\n"
            return f"received-{_IDENTITY}\n"
        if 'tell application "System Events"' in command:
            return "true" if self.input_ok else "false"
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
        return None


def _check(mac: FakeMac, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ssh_mac_terminal_bridge_check,
        "uuid4",
        lambda: SimpleNamespace(hex="b" * 32),
    )
    control = SshMacHostControl.__new__(SshMacHostControl)
    control._run = mac
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
        display_count=1,
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
    assert mac.crop_rectangles() == [layout.target, layout.target]


def test_bridge_crops_from_the_displays_own_corner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One Mac reports its only screen at global x=3584. Windows are placed in
    # that space; the crop measures from the display's own corner instead.
    mac = FakeMac(
        visible_frame=(3584, 0, 1280, 964),
        display=(1280, 1024),
        capture_origin=(3584, 0),
    )

    result = _check(mac, monkeypatch)

    assert result.ok is True
    assert mac.requested_bounds[0][0] == 3624
    assert mac.crop_rectangles() == [(40, 40, 1240, 770), (40, 40, 1240, 770)]


def test_bridge_crops_in_image_pixels_on_a_scaled_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(backing_scale=2.0)

    _check(mac, monkeypatch)

    layout = window_layout(_STANDARD_FRAME)
    doubled = tuple(value * 2 for value in layout.target)
    assert mac.crop_rectangles() == [doubled, doubled]


def test_bridge_recovers_a_window_terminal_restored_off_the_left_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    off_screen = (-1400, 90, 100, 820)
    mac = FakeMac(
        placement=lambda requested, attempt: off_screen if attempt == 0 else requested
    )

    result = _check(mac, monkeypatch)

    assert result.ok is True
    assert result.error_code is None
    assert off_screen in mac.placed_bounds
    for rectangle in mac.crop_rectangles():
        assert _STANDARD_FRAME.contains(rectangle), rectangle


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
    assert (
        diagnostics["recovery"]
        == (TERMINAL_CAPTURE_RECOVERY[TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE])
    )
    assert mac.crop_rectangles() == []


def test_bridge_records_capture_diagnostics_when_frames_never_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(captures=("c2FtZQ==", "c2FtZQ=="))

    result = _check(mac, monkeypatch)

    assert result.ok is False
    assert result.error_code == TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE
    diagnostics = result.evidence["capture_diagnostics"]
    assert "screencapture" in diagnostics["command"]
    assert "--cropOffset" in diagnostics["command"]
    assert diagnostics["exit_code"] == 0
    assert diagnostics["stderr"] == ""
    assert diagnostics["console_user"] == "yoke-test"
    assert diagnostics["display_locked"] is False
    assert diagnostics["display_count"] == 1
    assert diagnostics["frames_differed"] is False
    assert (
        diagnostics["recovery"]
        == (TERMINAL_CAPTURE_RECOVERY[TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE])
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
    assert (
        diagnostics["recovery"]
        == (TERMINAL_CAPTURE_RECOVERY[TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE])
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


def test_bridge_asks_the_graphical_session_for_the_display_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Geometry is a window-server fact, so it is read from the same session
    # whose windows are placed and whose pixels are captured.
    mac = FakeMac()

    _check(mac, monkeypatch)

    probe = next(
        command
        for command in mac.commands
        if "NSScreen" in command and "set targetTab to do script" in command
    )
    assert "yoke-gui-session-" in probe
    assert not any(
        command.startswith("/usr/bin/osascript -l JavaScript")
        for command in mac.commands
    ), "the geometry probe must not run straight over the transport"
