"""The answer a scripted macOS host gives to the display visible-frame probe."""

from __future__ import annotations

import json


DISPLAY_FRAME_PROBE_PREFIX = "/usr/bin/osascript -l JavaScript"


def display_frame_stdout(
    *,
    visible_frame: tuple[int, int, int, int] = (0, 25, 1920, 975),
    display: tuple[int, int] = (1920, 1080),
) -> str:
    """Return the JSON a host reports for its menu-bar display's usable region."""
    left, top, width, height = visible_frame
    return json.dumps(
        {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "display_width": display[0],
            "display_height": display[1],
        }
    )


__all__ = ["DISPLAY_FRAME_PROBE_PREFIX", "display_frame_stdout"]
