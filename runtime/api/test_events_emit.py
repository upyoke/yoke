"""Tests for yoke_core.domain.events -- non-fatal emission contract.

Covers the FR-2/AC-11 non-fatal contract for connection-mode emission.
Envelope construction and successful connection-mode emission live in
test_events.py.
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.events import emit_event
from runtime.api.fixtures.pg_testdb import test_database


# ---------------------------------------------------------------------------
# Fixtures (mirror test_events.py — kept local so this module owns its
# own DB schema dependency)
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Provide an isolated backend-aware connection with events schema."""
    with test_database() as c:
        yield c


# ---------------------------------------------------------------------------
# Non-fatal contract tests
# ---------------------------------------------------------------------------


class TestNonFatalContract:
    def test_emit_swallows_connection_errors(self, conn):
        """Simulating a table-not-found error returns a failed result."""
        conn.execute("DROP TABLE events")
        conn.commit()
        result = emit_event(
            "NoTable",
            event_kind="system",
            event_type="test",
            session_id="s1",
            conn=conn,
        )
        assert result.ok is False
        assert result.reason == "events_table_missing"
