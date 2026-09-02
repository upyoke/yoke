"""Resolve a macOS display's visible frame and lay windows out inside it."""

from __future__ import annotations

from dataclasses import dataclass
import json

from yoke_contracts.machine_qa_execution import (
    TERMINAL_CAPTURE_RECOVERY,
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE,
)
from yoke_harness.ssh_mac_gui_session import run_terminal_app_command
from yoke_harness.ssh_mac_terminal_app import (
    RunRemote,
    set_terminal_app_window_bounds,
)

# Window bounds live in NSScreen's global space, whose origin need not sit on
# any attached display: one Mac's only 1280x1024 screen lives at global x=3584,
# so a rectangle written as if the display started at the origin lands nowhere
# near it. A whole-display capture, though, produces an image whose own top-left
# pixel IS that display's corner. The script therefore reports two things in one
# space: the usable region, for placing windows, and that display's corner, so a
# placed rectangle can be converted into the captured image's pixels before it
# is cropped. On the common single-display Mac the corner is (0, 0) and the
# conversion is the identity.
_VISIBLE_FRAME_SCRIPT = """
ObjC.import('AppKit');
var screens = $.NSScreen.screens;
if (screens.count < 1) {
  throw new Error('no display is attached to this graphical session');
}
var main = screens.objectAtIndex(0);
var full = main.frame;
var visible = main.visibleFrame;
var flipHeight = full.size.height;
JSON.stringify({
  left: Math.round(visible.origin.x),
  top: Math.round(flipHeight - (visible.origin.y + visible.size.height)),
  width: Math.round(visible.size.width),
  height: Math.round(visible.size.height),
  capture_origin_x: Math.round(full.origin.x),
  capture_origin_y: Math.round(flipHeight - (full.origin.y + full.size.height)),
  display_width: Math.round(full.size.width),
  display_height: Math.round(full.size.height),
  display_count: Math.round(screens.count),
  backing_scale: main.backingScaleFactor
});
"""
_FRAME_PROBE_TIMEOUT_SECONDS = 30
_WINDOW_MARGIN = 40
_TARGET_WINDOW_SIZE = (1500, 730)
_HELPER_WINDOW_SIZE = (900, 120)
_HELPER_WINDOW_GAP = 20
DISPLAY_FRAME_RECOVERY = TERMINAL_CAPTURE_RECOVERY[
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE
]


class DisplayFrameUnavailable(RuntimeError):
    """The host could not report a usable region for its main display."""


@dataclass(frozen=True)
class DisplayFrame:
    """Where windows may go, and where the capture measures that region from."""

    left: int
    top: int
    width: int
    height: int
    display_width: int
    display_height: int
    display_count: int
    capture_origin: tuple[int, int] = (0, 0)
    backing_scale: float = 1.0

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def bounds(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def contains(self, bounds: tuple[int, int, int, int]) -> bool:
        """Report whether a non-empty rectangle lies wholly inside this frame."""
        left, top, right, bottom = bounds
        return (
            right > left
            and bottom > top
            and left >= self.left
            and top >= self.top
            and right <= self.right
            and bottom <= self.bottom
        )

    def capture_rectangle(
        self,
        bounds: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        """Convert placed window bounds into a display image's own pixels."""
        origin_x, origin_y = self.capture_origin
        left, top, right, bottom = bounds
        return (left - origin_x, top - origin_y, right - origin_x, bottom - origin_y)

    def anchored(self, bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Return the same-sized rectangle shifted to fit inside this frame."""
        left, top, right, bottom = bounds
        width = min(right - left, self.width)
        height = min(bottom - top, self.height)
        left = min(max(left, self.left), self.right - width)
        top = min(max(top, self.top), self.bottom - height)
        return (left, top, left + width, top + height)


@dataclass(frozen=True)
class WindowLayout:
    """Where the driven window and its capture helper go on this display."""

    target: tuple[int, int, int, int]
    helper: tuple[int, int, int, int]


def resolve_display_frame(run: RunRemote) -> DisplayFrame:
    """Ask the host's own graphical session where its windows may go.

    The question is asked from inside Terminal.app rather than over the
    transport because screen geometry is a window-server fact, and this is the
    session whose windows are placed and whose pixels are captured. A process
    outside it can be answered for a desktop it is not part of, and the answer
    only has to be wrong once for every rectangle computed from it to be wrong.
    """
    result = run_terminal_app_command(
        run,
        argv=["/usr/bin/osascript", "-l", "JavaScript", "-e", _VISIBLE_FRAME_SCRIPT],
        timeout=_FRAME_PROBE_TIMEOUT_SECONDS,
    )
    stderr = (getattr(result, "stderr", "") or "").strip()
    if result.returncode:
        raise DisplayFrameUnavailable(
            "macOS did not report a display visible frame "
            f"(osascript exit {result.returncode}: {stderr or 'no output'}); "
            + DISPLAY_FRAME_RECOVERY
        )
    try:
        payload = json.loads(result.stdout.strip())
        frame = DisplayFrame(
            left=int(payload["left"]),
            top=int(payload["top"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            display_width=int(payload["display_width"]),
            display_height=int(payload["display_height"]),
            display_count=int(payload["display_count"]),
            capture_origin=(
                int(payload["capture_origin_x"]),
                int(payload["capture_origin_y"]),
            ),
            backing_scale=float(payload["backing_scale"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DisplayFrameUnavailable(
            "macOS returned an unreadable display visible frame "
            f"({result.stdout.strip()!r}); " + DISPLAY_FRAME_RECOVERY
        ) from exc
    if frame.width <= 0 or frame.height <= 0:
        raise DisplayFrameUnavailable(
            f"macOS reported an empty display visible frame {frame.bounds()}; "
            + DISPLAY_FRAME_RECOVERY
        )
    return frame


def window_layout(frame: DisplayFrame) -> WindowLayout:
    """Place both windows inside *frame*, the helper clear of the target.

    A region capture records whatever the window server composited there, so
    the helper window that issues the capture is kept out of the rectangle it
    captures rather than merely sent behind it.
    """
    margin = min(_WINDOW_MARGIN, frame.width // 8, frame.height // 8)
    helper_width = min(_HELPER_WINDOW_SIZE[0], frame.width - 2 * margin)
    helper_height = min(_HELPER_WINDOW_SIZE[1], max(frame.height // 4, 1))
    helper_top = frame.bottom - helper_height
    target_width = min(_TARGET_WINDOW_SIZE[0], frame.width - 2 * margin)
    target_height = min(
        _TARGET_WINDOW_SIZE[1],
        max(helper_top - _HELPER_WINDOW_GAP - (frame.top + margin), 1),
    )
    return WindowLayout(
        target=(
            frame.left + margin,
            frame.top + margin,
            frame.left + margin + target_width,
            frame.top + margin + target_height,
        ),
        helper=(
            frame.left + margin,
            helper_top,
            frame.left + margin + helper_width,
            frame.bottom,
        ),
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
    observed = set_terminal_app_window_bounds(
        run,
        window_id=window_id,
        bounds=bounds,
    )
    if observed is None or frame.contains(observed):
        return observed
    return set_terminal_app_window_bounds(
        run,
        window_id=window_id,
        bounds=frame.anchored(observed),
    )


__all__ = [
    "DISPLAY_FRAME_RECOVERY",
    "DisplayFrame",
    "DisplayFrameUnavailable",
    "RunRemote",
    "WindowLayout",
    "place_terminal_app_window",
    "resolve_display_frame",
    "window_layout",
]
