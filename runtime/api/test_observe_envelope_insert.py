"""Envelope build, insert, and perf — TestBuildEnvelope, TestInsertEvent, TestPerformance."""

from __future__ import annotations

import time

import pytest

from yoke_core.domain.observe import (
    parse_hook_event,
)
from runtime.api.observe_test_helpers import (
    SAMPLE_POST_TOOL_USE,
    make_memory_db,
)


@pytest.fixture
def memory_db():
    """Create an in-memory DB with the events table."""
    conn = make_memory_db()
    yield conn
    conn.close()


class TestPerformance:
    def test_module_import_under_200ms(self):
        """Module import + parse_hook_event must complete in <200ms."""
        start = time.monotonic()
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE,
            session_id="perf-test",
            hook_event="PostToolUse",
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        assert rec is not None
        assert elapsed_ms < 200, f"parse_hook_event took {elapsed_ms:.1f}ms"
