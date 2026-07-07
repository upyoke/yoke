"""CLI-owner tests for the events write-time isolation contract.

Exercises the ``yoke_core.domain.emit_event`` CLI surface to confirm it
honors the same isolation gate as the native emitter (AC-2 capture
intent without sink, plus the synthetic_smoke lineage escape hatch).
"""

from __future__ import annotations

import pytest
from yoke_core.domain.events import SYNTHETIC_SMOKE_FLAG
from yoke_core.domain.events_crud import cmd_init as init_events_schema
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


# ---------------------------------------------------------------------------
# Integration test for the CLI emit_event.py owner
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_cli_db(tmp_path, monkeypatch):
    with init_test_db(tmp_path, apply_schema=init_events_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", str(db_path))
        yield str(db_path)


class TestCliEmitEventIsolation:
    """Exercise the CLI owner's refusal behavior."""

    def test_cli_refuses_capture_without_sink(
        self, isolated_cli_db, monkeypatch, capsys
    ):
        """The CLI owner must no longer fall through to canonical writes when
        capture intent is declared but no sink is configured."""
        from yoke_core.domain import emit_event as emit_event_cli

        # Route resolution to a temp DB so a fallthrough would be
        # observable as a row. With the gate wired in, no row should land.
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.delenv("YOKE_EVENTS_FILE", raising=False)
        # Isolation OFF for this case — we are specifically testing the
        # capture-intent-without-sink rule, which must fire independently.
        monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)

        rc = emit_event_cli.main(
            [
                "--name", "CliCaptureNoSink",
                "--kind", "system",
                "--type", "test",
                "--source-type", "backend",
                "--session-id", "test-cli-cap-1",
                "--event-id", "cli-cap-1",
            ]
        )
        assert rc == 0  # refused, but not a CLI error

        conn = connect_test_db(isolated_cli_db)
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_id = 'cli-cap-1'"
        ).fetchone()
        conn.close()
        assert row[0] == 0, "capture-without-sink must not leak to canonical"

        captured = capsys.readouterr()
        assert "refused" in captured.err

    def test_cli_allows_synthetic_smoke_through_isolation(
        self, isolated_cli_db, monkeypatch
    ):
        """synthetic_smoke lineage marker lets the CLI write through isolation."""
        from yoke_core.domain import emit_event as emit_event_cli

        monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
        monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
        monkeypatch.delenv("YOKE_EVENTS_FILE", raising=False)

        rc = emit_event_cli.main(
            [
                "--name", "CliSmoke",
                "--kind", "system",
                "--type", "smoke",
                "--source-type", "backend",
                "--session-id", "test-cli-smoke-1",
                "--event-id", "cli-smoke-1",
                "--anomaly-flags", SYNTHETIC_SMOKE_FLAG,
            ]
        )
        assert rc == 0

        conn = connect_test_db(isolated_cli_db)
        row = conn.execute(
            "SELECT anomaly_flags FROM events WHERE event_id = 'cli-smoke-1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert SYNTHETIC_SMOKE_FLAG in row[0]
