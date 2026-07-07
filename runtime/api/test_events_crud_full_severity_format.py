"""Direct API tests: severity_config CRUD, format-rows helper, exported constants."""

from __future__ import annotations

from yoke_core.domain import events_crud
from runtime.api.events_crud_full_test_helpers import (
    _insert_event_direct,
    _setup_severity_config,
)


class TestSeverityConfigCRUD:
    def test_set_and_retrieve(self, test_db):
        _setup_severity_config(test_db)
        test_db.execute(
            "INSERT INTO severity_config "
            "(event_name, source_type, min_severity, created_at) "
            "VALUES ('MyEvent', 'agent', 'ERROR', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(event_name, source_type) "
            "DO UPDATE SET min_severity=excluded.min_severity"
        )
        test_db.commit()

        row = test_db.execute(
            "SELECT min_severity FROM severity_config WHERE event_name='MyEvent'"
        ).fetchone()
        assert row[0] == "ERROR"

    def test_upsert_semantics(self, test_db):
        _setup_severity_config(test_db)
        test_db.execute(
            "INSERT INTO severity_config (event_name, source_type, min_severity, created_at) "
            "VALUES ('MyEvent', 'agent', 'WARN', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(event_name, source_type) DO UPDATE SET min_severity=excluded.min_severity"
        )
        test_db.execute(
            "INSERT INTO severity_config (event_name, source_type, min_severity, created_at) "
            "VALUES ('MyEvent', 'agent', 'ERROR', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(event_name, source_type) DO UPDATE SET min_severity=excluded.min_severity"
        )
        test_db.commit()

        count = test_db.execute(
            "SELECT COUNT(*) FROM severity_config WHERE event_name='MyEvent' AND source_type='agent'"
        ).fetchone()[0]
        assert count == 1

        val = test_db.execute(
            "SELECT min_severity FROM severity_config WHERE event_name='MyEvent'"
        ).fetchone()[0]
        assert val == "ERROR"

    def test_list_all(self, test_db):
        _setup_severity_config(test_db)
        test_db.execute(
            "INSERT INTO severity_config "
            "(event_name, source_type, min_severity, created_at) "
            "VALUES ('Evt1', 'agent', 'WARN', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(event_name, source_type) "
            "DO UPDATE SET min_severity=excluded.min_severity"
        )
        test_db.execute(
            "INSERT INTO severity_config "
            "(event_name, source_type, min_severity, created_at) "
            "VALUES ('Evt2', 'system', 'ERROR', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(event_name, source_type) "
            "DO UPDATE SET min_severity=excluded.min_severity"
        )
        test_db.commit()

        rows = test_db.execute(
            "SELECT * FROM severity_config ORDER BY event_name ASC"
        ).fetchall()
        # Default (*,*) + Evt1 + Evt2
        assert len(rows) == 3


class TestFormatHelpers:
    def test_format_rows_empty(self):
        assert events_crud._format_rows([]) == ""

    def test_format_rows_null_values(self, test_db):
        """NULL values render as empty strings."""
        _insert_event_direct(test_db, event_name="Test")
        rows = test_db.execute("SELECT id, event_name, anomaly_flags FROM events").fetchall()
        result = events_crud._format_rows(rows)
        # anomaly_flags is NULL -> empty
        parts = result.split("|")
        assert parts[-1] == ""  # NULL rendered as empty

    def test_format_rows_pipe_delimited(self, test_db):
        _insert_event_direct(test_db, event_name="Alpha")
        _insert_event_direct(test_db, event_name="Beta")
        rows = test_db.execute("SELECT event_name FROM events ORDER BY event_name").fetchall()
        result = events_crud._format_rows(rows)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0] == "Alpha"
        assert lines[1] == "Beta"


class TestConstants:
    def test_valid_source_types(self):
        expected = ("agent", "backend", "frontend", "system", "script", "hook", "skill")
        assert events_crud.VALID_SOURCE_TYPES == expected

    def test_valid_severities(self):
        expected = ("DEBUG", "INFO", "STATUS", "WARN", "ERROR", "FATAL")
        assert events_crud.VALID_SEVERITIES == expected

    def test_severity_order_complete(self):
        for sev in events_crud.VALID_SEVERITIES:
            assert sev in events_crud.SEVERITY_ORDER
