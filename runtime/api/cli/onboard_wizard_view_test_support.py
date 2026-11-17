"""Wait for an onboarding view to accept pilot input before driving it."""

from __future__ import annotations

import asyncio
from typing import Any

VIEW_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.05


async def wait_for_view(pilot: Any, key: str, selector: str) -> None:
    """Require the expected view's mounted, focused control within five seconds.

    Polls against a deadline instead of blocking on the app's workers, so a
    check that never finishes fails here, naming the current view, rather than
    as a cancelled worker.
    """
    app = pilot.app
    loop = asyncio.get_running_loop()
    deadline = loop.time() + VIEW_WAIT_SECONDS
    while True:
        controls = app.query(f"#onboard-body {selector}")
        if (
            not app._checking
            and all(worker.is_finished for worker in app.workers)
            and app._history[-1].prompt.key == key
            and controls
            and controls.first().is_mounted
            and controls.first().has_focus
            and not controls.first().disabled
        ):
            return
        if loop.time() >= deadline:
            raise AssertionError(
                f"waiting for {key} with focused {selector}; "
                f"current view: {app._history[-1].prompt.key}; "
                f"checking: {app._checking}; "
                f"mounted controls: {list(app.query('#onboard-body').first().children)!r}"
            )
        await pilot.pause(_POLL_SECONDS)
