"""Test-only live GitHub REST guard."""

from __future__ import annotations

import os
from typing import Callable


def block_live_test_call(active_urlopen: Callable, default_urlopen: Callable) -> None:
    """Raise when pytest reaches the real network transport by accident."""
    if os.environ.get("YOKE_TEST_ALLOW_LIVE_REST") == "1":
        return
    if (
        os.environ.get("YOKE_TEST_BLOCK_LIVE_REST") == "1"
        and active_urlopen is default_urlopen
    ):
        raise RuntimeError(
            "live GitHub REST call attempted from a test process. Mock "
            "gh_rest_transport.urlopen, use YOKE_REST_FAKE_DIR, or mock the "
            "typed GitHub REST function at the caller's import boundary."
        )


__all__ = ["block_live_test_call"]
