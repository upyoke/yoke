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


@pytest.fixture(autouse=True)
def _synthetic_selector_roots(request, monkeypatch):
    """Import-graph fixtures declare their own test universe explicitly."""
    if request.module.__name__.rsplit(".", 1)[-1].startswith("test_impacted"):
        from yoke_core.tools import (
            _impacted_import_index,
            _impacted_selection,
            watch_pytest_project_python,
        )
        from yoke_core.tools.impacted_project_test_roots import YOKE_SEEDED_TEST_ROOTS

        monkeypatch.setattr(
            _impacted_import_index, "current_test_roots", lambda: YOKE_SEEDED_TEST_ROOTS
        )
        monkeypatch.setattr(
            _impacted_selection, "current_test_roots", lambda: YOKE_SEEDED_TEST_ROOTS
        )
        monkeypatch.setattr(
            watch_pytest_project_python,
            "resolve_test_roots",
            lambda _checkout: YOKE_SEEDED_TEST_ROOTS,
        )
