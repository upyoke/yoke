"""Take the one frame the ``yoke onboard`` golden gates compare against.

Everything here exists so the exported frame is a function of the wizard's
state and nothing else. Two inputs would otherwise let the speed of the machine
reach the export: a screen still being drawn, and a scroll still moving.

A screen is treated as drawn only once two consecutive exports agree, because a
fixed number of pauses spends a budget and hopes. A scroll is snapped to the
cell its own content already occupies, because a container renders text at
``round(scroll_y)`` but hands its scrollbar the raw float — so a scroll resting
between two cells exports identical text beside a thumb that has crossed into
the next cell, and the gate fails on where a scroll stopped rather than on what
the wizard drew.

:mod:`onboard_wizard_golden_support` owns the other half — normalization, the
host-independent stub data, and the catalog<->golden parity scan.
"""

from __future__ import annotations

from typing import Any

# A fixed number of pauses cannot prove the UI stopped changing — it only
# spends a fixed budget hoping it did. Under CI load one more frame can still
# be pending, and the export then captures a half-settled screen: an extra
# style rule for an element rendered without its final colour, and clip
# dimensions from a viewport that had not finished scrolling. Capturing until
# two consecutive exports agree makes "settled" an observation rather than a
# guess, so the gate fails on real drift instead of on runner speed.
_SETTLE_ATTEMPTS = 8


def snap_scroll_offsets(app: Any) -> None:
    """Round every scroll offset to the cell its own content is drawn at.

    Rounding to the offset the content already uses cannot move a glyph; it only
    stops the scrollbar from disagreeing with the text beside it.
    """
    for widget in (app.screen, *app.screen.query("*")):
        snapped = round(widget.scroll_x), round(widget.scroll_y)
        if (widget.scroll_x, widget.scroll_y) != snapped:
            widget.scroll_x, widget.scroll_y = snapped


async def _stable_screenshot(pilot: Any, app: Any, title: str) -> str:
    """Export the screen once it stops changing between consecutive frames."""
    # A quiet message queue is not sufficient when Textual still has scheduled
    # UI work: two immediate exports can agree on the same intermediate
    # scrollbar style. Drain scheduled animations and their follow-up screen
    # messages before treating repeated SVG bytes as evidence of stability.
    await pilot.wait_for_scheduled_animations()
    snap_scroll_offsets(app)
    previous = app.export_screenshot(title=title)
    for _ in range(_SETTLE_ATTEMPTS):
        await pilot.pause()
        snap_scroll_offsets(app)
        current = app.export_screenshot(title=title)
        if current == previous:
            return current
        previous = current
    # Still moving after the budget: return the newest frame and let the
    # golden comparison report the difference rather than silently passing a
    # frame nobody looked at.
    return previous
