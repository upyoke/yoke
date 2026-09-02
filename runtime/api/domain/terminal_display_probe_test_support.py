"""The answer a scripted macOS host gives to the display visible-frame probe."""

from __future__ import annotations

import json


DISPLAY_FRAME_PROBE_MARKER = "JavaScript"


def display_frame_stdout(
    *,
    visible_frame: tuple[int, int, int, int] = (0, 25, 1920, 975),
    display: tuple[int, int] = (1920, 1080),
    capture_origin: tuple[int, int] = (0, 0),
    display_count: int = 1,
    backing_scale: float = 1.0,
) -> str:
    """Return the JSON a host reports for its main display's usable region."""
    left, top, width, height = visible_frame
    return json.dumps(
        {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "capture_origin_x": capture_origin[0],
            "capture_origin_y": capture_origin[1],
            "display_width": display[0],
            "display_height": display[1],
            "display_count": display_count,
            "backing_scale": backing_scale,
        }
    )


__all__ = ["DISPLAY_FRAME_PROBE_MARKER", "display_frame_stdout"]
