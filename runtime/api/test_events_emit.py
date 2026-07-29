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
        conn.execute("DROP TABLE events CASCADE")
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


class TestHttpsTransportBestEffort:
    def test_emit_degrades_when_active_transport_is_https(self, monkeypatch):
        """Over an https control plane with no caller-managed connection,
        emission returns a non-ok result with a distinct transport reason
        instead of raising or attempting a fatal local connect."""
        import yoke_core.domain.events as events_mod

        # Isolation gate would otherwise refuse first; disable it so the
        # https short-circuit is the deciding branch.
        monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        monkeypatch.setattr(events_mod, "_active_transport_is_https", lambda: True)

        result = emit_event(
            "AdvancePhaseCompleted",
            event_kind="workflow",
            event_type="advance_phase",
            session_id="s1",
        )
        assert result.ok is False
        assert result.reason == events_mod.TRANSPORT_NO_LOCAL_DB_REASON

    def test_emit_ignores_https_short_circuit_when_conn_supplied(self, conn):
        """A caller-managed connection is always honored — the https
        short-circuit only guards the no-connection path."""
        import yoke_core.domain.events as events_mod

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("YOKE_EVENTS_ISOLATION", raising=False)
            mp.setattr(events_mod, "_active_transport_is_https", lambda: True)
            result = emit_event(
                "AdvancePhaseCompleted",
                event_kind="workflow",
                event_type="advance_phase",
                session_id="s1",
                conn=conn,
            )
        assert result.ok is True
        assert result.reason != events_mod.TRANSPORT_NO_LOCAL_DB_REASON
