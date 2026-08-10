"""Take the one frame the ``yoke onboard`` golden gates compare against.

Everything here exists so the exported frame is a function of the wizard's
state and nothing else. Three inputs would otherwise let the speed of the
machine reach the export: a screen still being drawn, a scroll still moving,
and a scrollbar drawn from a different layout pass than the text beside it.

A screen is treated as drawn only once two consecutive exports agree, because a
fixed number of pauses spends a budget and hopes. A scroll is snapped to the
cell its own content already occupies, because a container renders text at
``round(scroll_y)`` but hands its scrollbar the raw float — so a scroll resting
between two cells exports identical text beside a thumb that has crossed into
the next cell. And every frame is assembled from a single layout pass: the
viewport is put where focus already is, each scrollbar's cached geometry is
restated from the container it belongs to, and the screen is recomposed before
the export. So the thumb and the text can never come from two different passes,
and the gate fails on what the wizard drew rather than on where a scroll came to
rest or on which pass drew the thumb.

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


def scroll_focused_into_view(app: Any) -> None:
    """Put the viewport where the focused widget is.

    A body swap focuses its interactive control and Textual schedules the
    matching scroll separately, so the viewport a screen comes to rest at is
    reached one turn after the screen itself. Doing it before every export makes
    that final viewport an explicit part of the frame instead of a race the
    capture has to win on its first try — a screen whose focus lands late is
    re-aimed on the next attempt rather than exported half-scrolled.
    """
    focused = app.focused
    if focused is not None:
        app.screen.scroll_to_widget(focused, animate=False, immediate=True)


def snap_scroll_offsets(app: Any) -> None:
    """Round every scroll offset to the cell its own content is drawn at.

    Rounding to the offset the content already uses cannot move a glyph; it only
    stops the scrollbar from disagreeing with the text beside it.
    """
    for widget in (app.screen, *app.screen.query("*")):
        snapped = round(widget.scroll_x), round(widget.scroll_y)
        if (widget.scroll_x, widget.scroll_y) != snapped:
            widget.scroll_x, widget.scroll_y = snapped


def sync_scrollbar_geometry(app: Any) -> None:
    """Draw each scrollbar from the numbers its own container is drawn from.

    A scrollbar keeps its own copies of the container's virtual size, window
    size and scroll position, and Textual refreshes those copies only when the
    container's own measurements change. A copy carried over from an earlier
    layout renders a thumb that disagrees with the text: a virtual size one row
    too tall stops the thumb short of the track, which adds a reversed end-cap
    glyph — and, because that glyph paints in the scrollbar's background colour,
    a style rule no other element on the screen uses. The gate then fails on a
    single extra colour declaration while every character matches.

    Restating the copies from the container cannot move a glyph the container
    drew; it only stops the bar and the text from coming from different passes.
    """
    for widget in (app.screen, *app.screen.query("*")):
        if not widget.is_scrollable:
            continue
        if widget.show_vertical_scrollbar:
            bar = widget.vertical_scrollbar
            bar.window_virtual_size = widget.virtual_size.height
            bar.window_size = (
                widget.container_size.height - widget.scrollbar_size_horizontal
            )
            bar.position = widget.scroll_y
        if widget.show_horizontal_scrollbar:
            bar = widget.horizontal_scrollbar
            bar.window_virtual_size = widget.virtual_size.width
            bar.window_size = (
                widget.container_size.width - widget.scrollbar_size_vertical
            )
            bar.position = widget.scroll_x


def compose_frame(app: Any, title: str) -> str:
    """Hold the frame still, compose it from one layout pass, and export it."""
    scroll_focused_into_view(app)
    snap_scroll_offsets(app)
    sync_scrollbar_geometry(app)
    # Textual recomposes on the next turn of the message loop, so an export
    # taken straight after a scroll shows the new thumb beside the old text.
    # Composing here removes that turn from the export entirely: whatever the
    # widgets currently say is what gets drawn.
    app.screen._refresh_layout()
    return app.export_screenshot(title=title)


async def _stable_screenshot(pilot: Any, app: Any, title: str) -> str:
    """Export the screen once it stops changing between consecutive frames."""
    # A quiet message queue is not sufficient when Textual still has scheduled
    # UI work: two immediate exports can agree on the same intermediate
    # scrollbar style. Drain scheduled animations and their follow-up screen
    # messages before treating repeated SVG bytes as evidence of stability.
    await pilot.wait_for_scheduled_animations()
    previous = compose_frame(app, title)
    for _ in range(_SETTLE_ATTEMPTS):
        await pilot.pause()
        current = compose_frame(app, title)
        if current == previous:
            return current
        previous = current
    # Still moving after the budget: return the newest frame and let the
    # golden comparison report the difference rather than silently passing a
    # frame nobody looked at.
    return previous
