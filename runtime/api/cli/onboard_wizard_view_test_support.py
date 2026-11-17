"""Wait for an onboarding view to accept pilot input before driving it."""

from __future__ import annotations

import asyncio
from typing import Any

from runtime.api.cli.onboard_wizard_test_helpers import settle_checks


async def wait_for_view(pilot: Any, key: str, selector: str) -> None:
    """Require the expected view's mounted, focused control within five seconds."""
    app = pilot.app
    try:
        async with asyncio.timeout(5):
            while True:
                await settle_checks(pilot)
                controls = app.query(f"#onboard-body {selector}")
                if (
                    app._history[-1].prompt.key == key
                    and controls
                    and controls.first().is_mounted
                    and controls.first().has_focus
                    and not controls.first().disabled
                ):
                    return
                await pilot.pause()
    except TimeoutError as exc:
        current = app._history[-1].prompt.key
        raise AssertionError(
            f"waiting for {key} with focused {selector}; current view: {current}; "
            f"mounted controls: {list(app.query('#onboard-body').first().children)!r}"
        ) from exc
