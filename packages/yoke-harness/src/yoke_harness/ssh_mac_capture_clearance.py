"""Keep the window that issues a capture off the window being captured.

The capture is a whole-display image cropped to the captured window, so any
window over that rectangle lands in the artifact. The capture command runs in
its own Terminal window, and Terminal opens that window wherever it restores
one -- often on top of the window under test. Before the command is released,
both windows' bounds are read back; an overlap is corrected by moving the
capture window clear and then by minimizing it, and an overlap that survives
both, or bounds that cannot be read, is named so the reviewer knows the image
is unreliable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_CAPTURE_DEGRADED_RECOVERY,
    TERMINAL_CAPTURE_WINDOW_BOUNDS_UNREADABLE_REASON,
    TERMINAL_CAPTURE_WINDOW_OVERLAPS_APP_REASON,
)
from yoke_harness.ssh_mac_display_frame import DisplayFrame
from yoke_harness.ssh_mac_terminal_app import (
    RunRemote,
    parse_window_bounds,
    run_osascript,
    set_terminal_app_window_bounds,
)

Bounds = tuple[int, int, int, int]
_GAP = 20


@dataclass(frozen=True)
class WindowState:
    """Where one Terminal window is, and whether it is minimized."""

    bounds: Bounds
    minimized: bool


@dataclass(frozen=True)
class Clearance:
    """The outcome of clearing the capture window, with what was observed."""

    degraded_reason: str | None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def detail(self) -> str | None:
        """One line naming the reason, the bounds, and the recovery."""
        if self.degraded_reason is None:
            return None
        return (
            f"{self.degraded_reason} (capture window "
            f"{self.evidence.get('capture_window')}, app window "
            f"{self.evidence.get('app_window')}); "
            + TERMINAL_CAPTURE_DEGRADED_RECOVERY[self.degraded_reason]
        )


def read_terminal_app_window(run: RunRemote, *, window_id: int) -> WindowState | None:
    """Read one window's bounds and minimized state, or None if unreadable."""
    result = run_osascript(
        run,
        [
            'tell application "Terminal"',
            f'if not (exists window id {window_id}) then return ""',
            f"set targetWindow to window id {window_id}",
            "set observed to bounds of targetWindow",
            "set observedState to (miniaturized of targetWindow) as text",
            'return observedState & "|" & ((item 1 of observed) as text) & "," & '
            '((item 2 of observed) as text) & "," & '
            '((item 3 of observed) as text) & "," & '
            "((item 4 of observed) as text)",
            "end tell",
        ],
    )
    if result.returncode:
        return None
    state, _separator, text = (result.stdout or "").strip().partition("|")
    bounds = parse_window_bounds(text)
    if bounds is None or state not in {"true", "false"}:
        return None
    return WindowState(bounds, state == "true")


def overlaps(first: Bounds, second: Bounds) -> bool:
    """Report whether two rectangles share any area."""
    return (
        first[0] < second[2]
        and second[0] < first[2]
        and first[1] < second[3]
        and second[1] < first[3]
    )


def clear_slot(app: Bounds, helper: Bounds, frame: DisplayFrame) -> Bounds | None:
    """Return the helper's rectangle moved below or above *app*, inside *frame*."""
    width, height = helper[2] - helper[0], helper[3] - helper[1]
    left = min(max(helper[0], frame.left), frame.right - width)
    for top in (app[3] + _GAP, app[1] - _GAP - height):
        slot = (left, top, left + width, top + height)
        if frame.contains(slot) and not overlaps(slot, app):
            return slot
    return None


def _minimize(run: RunRemote, *, window_id: int) -> None:
    run_osascript(
        run,
        [
            'tell application "Terminal"',
            f"if exists window id {window_id} then "
            f"set miniaturized of window id {window_id} to true",
            "end tell",
        ],
    )


def clear_capture_window(
    run: RunRemote,
    *,
    capture_window_id: int,
    app_window_id: int,
    frame: DisplayFrame,
) -> Clearance:
    """Make sure the capture window does not cover the app window."""
    steps: list[str] = []

    def observe() -> tuple[WindowState | None, WindowState | None, dict[str, Any]]:
        helper = read_terminal_app_window(run, window_id=capture_window_id)
        app = read_terminal_app_window(run, window_id=app_window_id)
        return (
            helper,
            app,
            {
                "capture_window": list(helper.bounds) if helper else None,
                "capture_window_minimized": helper.minimized if helper else None,
                "app_window": list(app.bounds) if app else None,
                "corrections": steps,
            },
        )

    def clear(helper: WindowState, app: WindowState) -> bool:
        return helper.minimized or not overlaps(helper.bounds, app.bounds)

    helper, app, evidence = observe()
    if helper is not None and app is not None and not clear(helper, app):
        slot = clear_slot(app.bounds, helper.bounds, frame)
        if slot is not None:
            steps.append(f"moved to {list(slot)}")
            set_terminal_app_window_bounds(run, window_id=capture_window_id, bounds=slot)
            helper, app, evidence = observe()
        if helper is not None and app is not None and not clear(helper, app):
            steps.append("minimized")
            _minimize(run, window_id=capture_window_id)
            helper, app, evidence = observe()
    if helper is None or app is None:
        return Clearance(TERMINAL_CAPTURE_WINDOW_BOUNDS_UNREADABLE_REASON, evidence)
    if not clear(helper, app):
        return Clearance(TERMINAL_CAPTURE_WINDOW_OVERLAPS_APP_REASON, evidence)
    return Clearance(None, evidence)


__all__ = [
    "Clearance",
    "WindowState",
    "clear_capture_window",
    "clear_slot",
    "overlaps",
    "read_terminal_app_window",
]
