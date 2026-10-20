"""The capture window is cleared off the captured window, or named as covering it."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import recipe
from runtime.api.domain.scripted_mac_host_test_support import ScriptedMacHost
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_CAPTURE_WINDOW_BOUNDS_UNREADABLE_REASON,
    TERMINAL_CAPTURE_WINDOW_OVERLAPS_APP_REASON,
)
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe
from yoke_harness.ssh_mac_display_frame import DisplayFrame, window_layout
from yoke_harness.ssh_mac_terminal_app import open_terminal_app_window
from yoke_harness.ssh_mac_terminal_screenshot import capture_terminal_app_region


_FRAME = DisplayFrame(
    left=0,
    top=25,
    width=1920,
    height=975,
    display_width=1920,
    display_height=1080,
    display_count=1,
)
_LAYOUT = window_layout(_FRAME)
# Where Terminal restored the capture window in the failed welcome-frame run:
# across the top of the window under test.
_RESTORED_OVER_APP = (600, 65, 1500, 185)
_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nuser-visible").decode("ascii")


class _Host(ScriptedMacHost):
    """A host whose Terminal puts the capture window where the test says."""

    def __init__(
        self,
        *,
        moves_land_over_app: bool = False,
        minimize_works: bool = True,
        capture_window_readable: bool = True,
        transcript: str | None = None,
    ) -> None:
        super().__init__()
        self.moves_land_over_app = moves_land_over_app
        self.minimize_works = minimize_works
        self.capture_window_readable = capture_window_readable
        self.transcript = transcript

    def place(self, requested, attempt):
        if requested == _LAYOUT.target:
            return requested
        if requested == _LAYOUT.helper or self.moves_land_over_app:
            return _RESTORED_OVER_APP
        return requested

    def window_state(self, window_id):
        if window_id == self.window_ids[-1] and not self.capture_window_readable:
            return None
        if not self.minimize_works:
            self.minimized.discard(window_id)
        return super().window_state(window_id)

    def reply(self, command):
        if command.startswith("/bin/test -s "):
            return _PNG
        if self.transcript is not None and "return contents of selected tab" in command:
            return self.transcript
        if 'tell application "System Events"' in command:
            return "true"
        if command.startswith("cat /tmp/yoke-qa-"):
            return "0\n"
        return None

    def gate_released_after_read_back(self) -> bool:
        reads = [i for i, c in enumerate(self.commands) if "observedState" in c]
        touches = [
            i
            for i, c in enumerate(self.commands)
            if c.startswith("/usr/bin/touch ") and c.endswith(".gate")
        ]
        return bool(reads and touches) and max(reads) < touches[0]


def _capture(host: _Host):
    app = open_terminal_app_window(host, command="app", bounds=_LAYOUT.target)
    assert app.window_id is not None
    assert app.bounds == _LAYOUT.target
    return capture_terminal_app_region(
        host,
        remote="/tmp/clearance.png",
        window_id=app.window_id,
        frame=_FRAME,
        layout=_LAYOUT,
    )


def test_an_overlapping_capture_window_is_moved_clear_before_the_capture() -> None:
    host = _Host()

    capture = _capture(host)

    assert capture.payload == _PNG
    assert capture.degraded_detail is None
    clearance = capture.diagnostics["capture_window_clearance"]
    assert clearance["degraded_reason"] is None
    assert clearance["corrections"] == ["moved to [600, 815, 1500, 935]"]
    assert clearance["capture_window"] == [600, 815, 1500, 935]
    assert clearance["app_window"] == list(_LAYOUT.target)
    assert host.gate_released_after_read_back()


def test_a_capture_window_that_will_not_move_is_minimized() -> None:
    host = _Host(moves_land_over_app=True)

    capture = _capture(host)

    assert capture.degraded_detail is None
    clearance = capture.diagnostics["capture_window_clearance"]
    assert clearance["corrections"][-1] == "minimized"
    assert clearance["capture_window_minimized"] is True


def test_an_overlap_that_persists_names_the_degraded_reason_with_bounds() -> None:
    host = _Host(moves_land_over_app=True, minimize_works=False)

    capture = _capture(host)

    # The image is still kept; the reason says why it cannot be trusted.
    assert capture.payload == _PNG
    assert capture.degraded_detail is not None
    assert capture.degraded_detail.startswith(
        TERMINAL_CAPTURE_WINDOW_OVERLAPS_APP_REASON
    )
    assert str(list(_RESTORED_OVER_APP)) in capture.degraded_detail
    assert str(list(_LAYOUT.target)) in capture.degraded_detail
    assert "transcript" in capture.degraded_detail
    assert host.gate_released_after_read_back()


def test_an_unreadable_capture_window_names_the_degraded_reason() -> None:
    host = _Host(capture_window_readable=False)

    capture = _capture(host)

    assert capture.payload == _PNG
    assert capture.degraded_detail is not None
    assert capture.degraded_detail.startswith(
        TERMINAL_CAPTURE_WINDOW_BOUNDS_UNREADABLE_REASON
    )
    clearance = capture.diagnostics["capture_window_clearance"]
    assert clearance["capture_window"] is None
    assert host.gate_released_after_read_back()


def test_the_recipe_records_a_persisting_overlap_as_capture_degraded_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.uuid4",
        lambda: SimpleNamespace(hex="c" * 32),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.time.sleep",
        lambda _seconds: None,
    )
    config = recipe(mode="terminal")
    config["actions"] = [{"step": "done", "keys": [], "capture": True}]
    config["capture_checkpoints"] = ["done"]
    host = _Host(moves_land_over_app=True, minimize_works=False, transcript="ready")

    result = execute_terminal_recipe(
        host,
        yoke_bin="yoke",
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke setup",
        required_completion="done",
        config=config,
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
    )

    reason = result.evidence["capture_degraded_reason"]
    assert reason.startswith(f"done: {TERMINAL_CAPTURE_WINDOW_OVERLAPS_APP_REASON}")
    step = result.evidence["steps"][0]
    assert step["artifact_handle"]["content_type"] == "image/png"
    clearance = step["screenshot_diagnostics"]["capture_window_clearance"]
    assert clearance["degraded_reason"] == TERMINAL_CAPTURE_WINDOW_OVERLAPS_APP_REASON
