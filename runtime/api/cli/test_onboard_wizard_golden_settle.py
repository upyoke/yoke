"""The golden screenshot is taken once the screen stops changing.

A fixed number of pauses spends a budget and hopes the UI settled. Under CI
load a frame can still be pending, and the export then captures a half-settled
screen — which is how a golden gate starts failing on runner speed rather than
on real drift.
"""

from __future__ import annotations

import asyncio

from runtime.api.cli import onboard_wizard_golden_support as support


class _App:
    """Stands in for the wizard app, returning a scripted frame sequence."""

    def __init__(self, frames: list[str]) -> None:
        self._frames = frames
        self.exports = 0

    def export_screenshot(self, *, title: str) -> str:
        self.exports += 1
        index = min(self.exports - 1, len(self._frames) - 1)
        return self._frames[index]


class _Pilot:
    def __init__(self) -> None:
        self.pauses = 0
        self.scheduled_animation_waits = 0

    async def wait_for_scheduled_animations(self) -> None:
        self.scheduled_animation_waits += 1

    async def pause(self) -> None:
        self.pauses += 1


def _settle(frames: list[str]) -> tuple[str, _App, _Pilot]:
    app, pilot = _App(frames), _Pilot()
    result = asyncio.run(support._stable_screenshot(pilot, app, "t"))
    return result, app, pilot


def test_returns_as_soon_as_two_frames_agree() -> None:
    result, app, pilot = _settle(["settled", "settled"])

    assert result == "settled"
    assert app.exports == 2
    assert pilot.scheduled_animation_waits == 1
    assert pilot.pauses == 1


def test_keeps_waiting_while_the_screen_is_still_changing() -> None:
    # The failure this guards: an early frame carries an extra style rule and
    # clip dimensions from a viewport that had not finished scrolling.
    result, app, pilot = _settle(["half-drawn", "scrolling", "final", "final"])

    assert result == "final"
    assert pilot.scheduled_animation_waits == 1
    assert pilot.pauses == 3


def test_gives_up_bounded_rather_than_hanging() -> None:
    # A screen that genuinely never settles must not wedge the suite; the
    # newest frame goes to the comparison so the gate reports the difference.
    never_settles = [f"frame-{n}" for n in range(100)]

    result, _app, pilot = _settle(never_settles)

    assert pilot.scheduled_animation_waits == 1
    assert pilot.pauses == support._SETTLE_ATTEMPTS
    assert result == f"frame-{support._SETTLE_ATTEMPTS}"
