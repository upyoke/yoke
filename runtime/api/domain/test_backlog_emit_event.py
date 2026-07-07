"""Focused tests for backlog event emission hardening."""

from __future__ import annotations

import builtins
import sys
from unittest import mock

from yoke_core.domain import backlog


class TestBacklogEmitEventNonFatal:
    """backlog._emit_event must stay non-fatal when imports fail late."""

    def test_import_error_warns_and_returns(self, capsys):
        """ImportError produces a warning instead of aborting the caller."""
        real_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name == "yoke_core.domain.events":
                raise ImportError("Simulated: module unavailable")
            return real_import(name, *args, **kwargs)

        saved = sys.modules.pop("yoke_core.domain.events", None)
        try:
            with mock.patch("builtins.__import__", side_effect=blocking_import):
                backlog._emit_event(
                    "TestEvent", 999, {"test": True}, out=sys.stderr
                )
        finally:
            if saved is not None:
                sys.modules["yoke_core.domain.events"] = saved

        captured = capsys.readouterr()
        assert "event emission skipped" in captured.err
        assert "999" in captured.err

    def test_normal_emit_still_uses_native_emitter(self):
        """When imports work, backlog._emit_event still calls the emitter."""
        sentinel = {"called": False}

        def fake_emit(*args, **kwargs):
            sentinel["called"] = True
            return {"event_id": "test-id"}

        with mock.patch(
            "yoke_core.domain.events.emit_event",
            side_effect=fake_emit,
        ):
            backlog._emit_event("TestEvent", 999, {"test": True})

        assert sentinel["called"]
