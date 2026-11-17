"""Close the macOS identity browsers before a capture or reset touches them.

The identity profiles are the test machine's only login store. Chromium writes
a profile's cookie store as it closes, so a store kept while it runs can miss
the newest sign-in, and a running browser writes its in-memory state back
over a home restored under it. Capture and reset therefore close every
identity browser first, gracefully through its DevTools port: a forced kill
would discard the cookies being saved.
"""

from __future__ import annotations

from typing import Callable

from yoke_harness.identity_browser_approval import (
    HELPER_UNREADABLE,
    close_identity_browsers,
)
from yoke_contracts.test_machine_types import HostActionResult

SIGN_IN_APP_QUIT_NOT_PROVED = "test_machine_sign_in_app_quit_not_proved"
SIGN_IN_APP_PROBE_FAILED = "test_machine_sign_in_app_probe_failed"
IDENTITY_BROWSER = "identity browser"


def quit_sign_in_apps(run: Callable[..., object], user: str) -> HostActionResult:
    """Close each running identity browser and prove it exited."""
    del user  # The store is the SSH user's own; no other user's browser is touched.
    receipt = close_identity_browsers(run)
    if receipt.get("ok"):
        return HostActionResult(
            True,
            {"sign_in_apps_quit": [IDENTITY_BROWSER] if receipt.get("browsers") else []},
        )
    reason = receipt.get("reason")
    evidence = {k: v for k, v in receipt.items() if k not in {"ok", "reason"}}
    return HostActionResult(
        False,
        {"app": IDENTITY_BROWSER, "reason": reason, **evidence},
        SIGN_IN_APP_PROBE_FAILED
        if reason in {HELPER_UNREADABLE, "identity_browser_devtools_failed"}
        else SIGN_IN_APP_QUIT_NOT_PROVED,
    )


__all__ = [
    "SIGN_IN_APP_PROBE_FAILED",
    "SIGN_IN_APP_QUIT_NOT_PROVED",
    "quit_sign_in_apps",
]
