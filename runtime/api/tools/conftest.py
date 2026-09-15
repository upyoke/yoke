"""Watcher-test defaults for a caller whose harness has a native idle wake."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

from yoke_core.tools import _watch_streaming_pair
from yoke_core.tools._watch_wait_mode import WatchWaitMode


@pytest.fixture(autouse=True)
def _without_inherited_relay_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never inherit the launching worker's own headless markers.

    A suite run from inside a relay-launched worker carries that
    worker's launch context, which makes every watcher under test read
    as headless and emit the continuation notice. Tests that mean to be
    headless set the marker themselves, after this fixture clears it.
    """
    monkeypatch.delenv(LAUNCH_CONTEXT_ENV, raising=False)
    monkeypatch.delenv(RESUME_ATTEMPT_ENV, raising=False)


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
