"""Wait for an onboarding view to accept pilot input before driving it."""

from __future__ import annotations

import asyncio
from typing import Any

VIEW_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.05


async def wait_for_view(
    pilot: Any, key: str, selector: str | None = None, *, checking: bool = False
) -> None:
    """Wait for a mounted view and, when specified, its focused control.

    Checking screens have no input and may remain on screen until the test
    releases the worker. Pass checking=True to wait for that intermediate view.

    Polls against a deadline instead of blocking on the app's workers, so a
    check that never finishes fails here, naming the current view, rather than
    as a cancelled worker.
    """
    app = pilot.app
    loop = asyncio.get_running_loop()
    deadline = loop.time() + VIEW_WAIT_SECONDS
    target = selector or ".onboard-title"
    while True:
        controls = app.query(f"#onboard-body {target}")
        control = controls.first() if controls else None
        if (
            app._checking == checking
            and (checking or all(worker.is_finished for worker in app.workers))
            and not app._swap_pending
            and not app._body_swap_active
            and app._history[-1].prompt.key == key
            and control is not None
            and control.is_mounted
            and (selector is None or (control.has_focus and not control.disabled))
        ):
            return
        if loop.time() >= deadline:
            raise AssertionError(
                f"waiting for {key} with {target}; "
                f"current view: {app._history[-1].prompt.key}; "
                f"checking: {app._checking}; "
                f"mounted controls: {list(app.query('#onboard-body').first().children)!r}"
            )
        await pilot.pause(_POLL_SECONDS)
