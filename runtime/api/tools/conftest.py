"""Watcher-test defaults for a caller whose harness has a native idle wake."""

from __future__ import annotations

import pytest

from yoke_core.tools import _watch_streaming_pair
from yoke_core.tools._watch_wait_mode import WatchWaitMode


@pytest.fixture(autouse=True)
def _wakeable_watcher_test_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy pair-shape tests explicit about their wakeable caller."""
    monkeypatch.setattr(
        _watch_streaming_pair,
        "resolve_wait_mode",
        lambda: WatchWaitMode(
            name="background-wake",
            reason="test caller records agent_wake.idle_wake=supported",
            wake_mechanism="Monitor",
        ),
    )
