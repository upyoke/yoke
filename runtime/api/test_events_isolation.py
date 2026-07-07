"""Tests for the events write-time isolation contract.

Covers AC-2, AC-5, AC-6, AC-7: the isolation gate in
``yoke_core.domain.events`` must refuse live-ledger writes when the
process declares ``YOKE_EVENTS_ISOLATION=1`` or ``YOKE_EVENTS_CAPTURE=1``
without ``YOKE_EVENTS_FILE``, and must honor the documented escape hatches
(explicit Postgres test DB authority, explicit ``conn=``, capture sink,
``synthetic_smoke`` lineage marker).
"""

from __future__ import annotations

import json
import pytest

from yoke_core.domain import events as events_mod
from yoke_core.domain import db_backend
from yoke_core.domain.events import (
    SYNTHETIC_SMOKE_FLAG,
    emit_event,
    isolation_gate_blocks,
)
from yoke_core.domain.events_crud import (
    cmd_init as init_events_schema,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


# ---------------------------------------------------------------------------
# Unit tests for isolation_gate_blocks (pure function)
# ---------------------------------------------------------------------------


class TestIsolationGateBlocks:
    """Unit tests for the isolation gate decision logic."""

    def _set_pg_dbname(self, monkeypatch, dbname: str) -> None:
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            f"host=/tmp/yoke-test user=yoketest dbname={dbname}",
        )
        monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)

    def test_gate_open_when_isolation_off(self, monkeypatch):
        monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is False
        )

    def test_gate_blocks_live_postgres_authority_under_isolation(self, monkeypatch):
        self._set_pg_dbname(monkeypatch, "yoke_prod")
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is True
        )

    def test_gate_allows_explicit_postgres_test_authority(self, monkeypatch):
        self._set_pg_dbname(
            monkeypatch, f"{db_backend.POSTGRES_TEST_DB_PREFIX}unit"
        )
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is False
        )

    def test_gate_allows_explicit_conn(self, monkeypatch):
        self._set_pg_dbname(monkeypatch, "yoke_prod")
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=None,
                has_explicit_conn=True,
            )
            is False
        )

    def test_gate_allows_synthetic_smoke_lineage(self, monkeypatch):
        self._set_pg_dbname(monkeypatch, "yoke_prod")
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=SYNTHETIC_SMOKE_FLAG,
                has_explicit_conn=False,
            )
            is False
        )

    def test_gate_matches_smoke_flag_in_comma_list(self, monkeypatch):
        self._set_pg_dbname(monkeypatch, "yoke_prod")
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=f"unregistered_event,{SYNTHETIC_SMOKE_FLAG}",
                has_explicit_conn=False,
            )
            is False
        )

    def test_gate_allows_capture_with_sink(self, monkeypatch, tmp_path):
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.setenv("YOKE_EVENTS_FILE", str(tmp_path / "cap.ndjson"))
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is False
        )

    def test_gate_blocks_capture_without_sink_even_without_isolation(
        self, monkeypatch
    ):
        """AC-2: capture-intent-without-sink is always refused."""
        monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.delenv("YOKE_EVENTS_FILE", raising=False)
        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is True
        )

    def test_gate_blocks_capture_without_sink_even_with_explicit_db(
        self, monkeypatch, tmp_path
    ):
        """Capture-without-sink is unconditional — even an explicit DB can't rescue it."""
        monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.delenv("YOKE_EVENTS_FILE", raising=False)
        temp_db = tmp_path / "fake.db"
        temp_db.touch()
        assert (
            isolation_gate_blocks(
                db_path=str(temp_db),
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is True
        )


# ---------------------------------------------------------------------------
# Integration tests for events.emit_event
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_temp_db(tmp_path, monkeypatch):
    """Temp DB the isolation gate can recognize as explicit test authority."""
    with init_test_db(tmp_path, apply_schema=init_events_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", str(db_path))
        yield str(db_path)


class TestEmitEventIsolation:
    """Integration tests exercising the gate end-to-end via emit_event."""

    def test_isolation_allows_write_to_explicit_temp_db(
        self, isolated_temp_db, monkeypatch
    ):
        # isolation is already set by conftest autouse fixture; assert anyway
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        result = emit_event(
            "IsolatedEmit",
            event_kind="system",
            event_type="test",
            session_id="test-isolation-1",
        )
        assert result is not None
        assert result["event_name"] == "IsolatedEmit"

        conn = connect_test_db(isolated_temp_db)
        row = conn.execute(
            "SELECT event_name FROM events WHERE event_id = %s",
            (result["event_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "IsolatedEmit"

    def test_isolation_refuses_live_authority_without_escape_hatch(
        self, monkeypatch
    ):
        """A live Postgres authority under isolation is refused."""
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/yoke-live user=yoke dbname=yoke_prod",
        )
        monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_FILE", raising=False)

        result = emit_event(
            "LeakAttempt",
            event_kind="system",
            event_type="test",
            session_id="test-leak-1",
        )
        assert result.ok is False
        assert result.reason == "isolation_gate_refused"

    def test_isolation_allows_synthetic_smoke_tagged_write(
        self, isolated_temp_db, monkeypatch
    ):
        """synthetic_smoke lineage marker lets the row into the live ledger."""
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)

        # Use an explicit isolated test authority even though the gate would
        # allow a live-ledger write.
        conn = connect_test_db(isolated_temp_db)
        try:
            result = emit_event(
                "SmokeTagged",
                event_kind="system",
                event_type="smoke",
                session_id="test-smoke-1",
                anomaly_flags=SYNTHETIC_SMOKE_FLAG,
                conn=conn,
            )
            assert result is not None
            row = conn.execute(
                "SELECT anomaly_flags FROM events WHERE event_id = %s",
                (result["event_id"],),
            ).fetchone()
            assert row is not None
            assert row[0] == SYNTHETIC_SMOKE_FLAG
        finally:
            conn.close()

    def test_capture_mode_without_sink_drops_native_emit(self, monkeypatch):
        """AC-2: YOKE_EVENTS_CAPTURE=1 with no file refuses emission."""
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.delenv("YOKE_EVENTS_FILE", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)
        monkeypatch.delenv("YOKE_DB", raising=False)

        result = emit_event(
            "CaptureNoSink",
            event_kind="system",
            event_type="test",
            session_id="test-capture-1",
        )
        assert result.ok is False
        assert result.reason == "isolation_gate_refused"

    def test_capture_mode_with_sink_writes_ndjson_natively(
        self, monkeypatch, tmp_path
    ):
        """Capture sinks short-circuit DB writes in the native emitter too."""
        sink = tmp_path / "cap.ndjson"
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.setenv("YOKE_EVENTS_FILE", str(sink))
        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_DB", raising=False)

        def _unexpected_write(*args, **kwargs):
            raise AssertionError("capture sink should bypass DB writes entirely")

        monkeypatch.setattr(events_mod, "_write_event", _unexpected_write)

        result = emit_event(
            "CaptureWithSink",
            event_kind="system",
            event_type="test",
            session_id="test-capture-sink",
        )
        assert result is not None

        lines = sink.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        envelope = json.loads(lines[0])
        assert envelope["event_name"] == "CaptureWithSink"
        assert envelope["event_id"] == result["event_id"]
