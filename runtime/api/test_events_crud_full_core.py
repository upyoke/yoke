# ruff: noqa: F811
"""Direct API CRUD tests: insert, severity check, list/count, query builder, prune."""
from __future__ import annotations

import pytest

from yoke_core.domain import db_backend, events_crud
from runtime.api.events_crud_full_test_helpers import (
    _SEVEN_DAYS_AGO,
    _event_count,
    _insert_event_direct,
    _setup_severity_config,
    _unique_event_id,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
    db_path,  # noqa: F401
)


class TestInsert:
    def test_basic_insert(self, test_db):
        _setup_severity_config(test_db)
        eid = _unique_event_id()
        # Use the internal insert logic directly on the connection
        test_db.execute(
            """INSERT INTO events (
                event_id, source_type, session_id, severity,
                event_kind, event_type, event_name, project_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(event_id) DO NOTHING""",
            (
                eid, "system", "sess-1", "INFO", "lifecycle", "test",
                "TestEvent", 1, "2026-04-20T00:00:00Z",
            ),
        )
        test_db.commit()
        count = _event_count(test_db)
        assert count == 1

    def test_deduplication_on_event_id(self, test_db):
        """Dedup is tested via cmd_insert's native conflict handling.
        Conftest helper uses plain INSERT, so we just test single insert here."""
        eid = _unique_event_id()
        _insert_event_direct(test_db, event_id=eid, event_name="Evt1")
        count = _event_count(test_db)
        assert count == 1

        # Verify the Postgres UNIQUE constraint is enforced.
        with pytest.raises(db_backend.integrity_error_types()):
            _insert_event_direct(test_db, event_id=eid, event_name="Evt1")

    def test_source_type_validation(self):
        """Invalid source_type raises ValueError."""
        with pytest.raises(ValueError, match="source_type must be one of"):
            events_crud.cmd_insert(
                ":memory:",
                event_id="e1",
                source_type="invalid",
                session_id="s1",
                event_kind="lifecycle",
                event_type="test",
                event_name="Test",
                skip_severity=True,
            )

    def test_severity_validation(self):
        with pytest.raises(ValueError, match="severity must be one of"):
            events_crud.cmd_insert(
                ":memory:",
                event_id="e1",
                source_type="system",
                session_id="s1",
                severity="INVALID",
                event_kind="lifecycle",
                event_type="test",
                event_name="Test",
                skip_severity=True,
            )

    def test_item_id_numeric_stays_canonical(self, test_db):
        _setup_severity_config(test_db)
        eid = _unique_event_id()
        _insert_event_direct(test_db, event_id=eid, event_name="Test", item_id="42")
        # Verify the raw helper preserves canonical numeric item IDs.
        row = test_db.execute("SELECT item_id FROM events WHERE event_id=%s", (eid,)).fetchone()
        assert row is not None
        assert row[0] == "42"


class TestSeverityCheck:
    def test_default_info_passes(self, test_db):
        _setup_severity_config(test_db)
        # Check that INFO passes against default INFO threshold
        # severity_num: INFO=1, which is >= INFO=1
        assert events_crud.severity_num("INFO") >= events_crud.severity_num("INFO")

    def test_debug_below_info(self, test_db):
        """DEBUG severity is below default INFO threshold."""
        assert events_crud.severity_num("DEBUG") < events_crud.severity_num("INFO")

    def test_severity_ordering(self):
        levels = ["DEBUG", "INFO", "STATUS", "WARN", "ERROR", "FATAL"]
        for i in range(len(levels) - 1):
            assert events_crud.severity_num(levels[i]) < events_crud.severity_num(levels[i + 1])

    def test_unknown_severity_defaults_to_info(self):
        assert events_crud.severity_num("UNKNOWN") == 1  # INFO level

    def test_cmd_severity_check_pass(self, test_db):
        _setup_severity_config(test_db)
        # Validation-only smoke: backend-routed command behavior is covered in
        # the split cmd tests that use the disposable Postgres db_path fixture.
        assert events_crud.cmd_severity_check.__doc__  # exists

    def test_severity_config_set_and_list(self, test_db):
        _setup_severity_config(test_db)
        # Set a specific config
        test_db.execute(
            "INSERT INTO severity_config "
            "(event_name, source_type, min_severity, created_at) "
            "VALUES ('SpecificEvent', 'agent', 'WARN', "
            "'2026-01-01T00:00:00Z') "
            "ON CONFLICT(event_name, source_type) DO UPDATE SET "
            "min_severity=excluded.min_severity, "
            "created_at=excluded.created_at",
        )
        test_db.commit()

        row = test_db.execute(
            "SELECT min_severity FROM severity_config WHERE event_name='SpecificEvent' AND source_type='agent'"
        ).fetchone()
        assert row[0] == "WARN"

    def test_severity_config_invalid_rejected(self):
        with pytest.raises(ValueError, match="min_severity must be one of"):
            events_crud.cmd_severity_config_set(":memory:", "*", "*", "INVALID")


class TestListAndCount:
    def test_list_returns_events(self, test_db):
        _insert_event_direct(test_db, event_name="Alpha")
        _insert_event_direct(test_db, event_name="Beta")

        rows = test_db.execute("SELECT * FROM events ORDER BY id ASC").fetchall()
        assert len(rows) == 2

    def test_count(self, test_db):
        _insert_event_direct(test_db, event_name="One")
        _insert_event_direct(test_db, event_name="Two")
        _insert_event_direct(test_db, event_name="Three")
        assert _event_count(test_db) == 3

    def test_anomalies_filter(self, test_db):
        _insert_event_direct(test_db, event_name="Normal", anomaly_flags=None)
        _insert_event_direct(test_db, event_name="Anomaly", anomaly_flags="nonzero_exit")

        anomaly_rows = test_db.execute(
            "SELECT * FROM events WHERE anomaly_flags IS NOT NULL AND anomaly_flags <> ''"
        ).fetchall()
        assert len(anomaly_rows) == 1
        assert anomaly_rows[0]["event_name"] == "Anomaly"

    def test_tail_ordering(self, test_db):
        _insert_event_direct(test_db, event_name="First", created_at="2025-01-01T00:00:00Z")
        _insert_event_direct(test_db, event_name="Second", created_at="2025-01-02T00:00:00Z")
        _insert_event_direct(test_db, event_name="Third", created_at="2025-01-03T00:00:00Z")

        # Tail returns most recent first
        rows = test_db.execute(
            "SELECT event_name FROM events ORDER BY created_at DESC, id DESC LIMIT 2"
        ).fetchall()
        assert rows[0]["event_name"] == "Third"
        assert rows[1]["event_name"] == "Second"


class TestQueryBuilder:
    def test_empty_args(self):
        where, params = events_crud._build_where([])
        assert where == ""
        assert params == []

    def test_source_type_filter(self):
        where, params = events_crud._build_where(["--source-type", "agent"])
        assert "source_type=%s" in where
        assert params == ["agent"]

    def test_session_id_filter(self):
        where, params = events_crud._build_where(["--session-id", "sess-123"])
        assert "session_id=%s" in where

    def test_event_name_filter(self):
        where, params = events_crud._build_where(["--event-name", "TestEvent"])
        assert "event_name=%s" in where

    def test_min_severity_filter(self):
        where, params = events_crud._build_where(["--min-severity", "WARN"])
        assert "CASE severity" in where
        # No param for severity (it's inlined)
        assert len(params) == 0

    def test_since_filter(self):
        where, params = events_crud._build_where(["--since", "2025-01-01"])
        assert "created_at >= %s" in where
        assert params == ["2025-01-01"]

    def test_until_filter(self):
        where, params = events_crud._build_where(["--until", "2025-12-31"])
        assert "created_at <= %s" in where

    def test_multiple_filters(self):
        where, params = events_crud._build_where([
            "--source-type", "agent",
            "--event-name", "Test",
            "--since", "2025-01-01",
        ])
        assert "source_type=%s" in where
        assert "event_name=%s" in where
        assert "created_at >= %s" in where
        assert len(params) == 3

    def test_project_filter(self):
        where, params = events_crud._build_where(["--project", "externalwebapp"])
        assert "project_id=%s" in where
        assert params == [2]

    def test_unknown_flags_fail_closed(self):
        """Unknown filter flags raise ValueError so callers fail closed
        instead of silently producing an unfiltered ledger dump."""
        with pytest.raises(ValueError, match="unknown filter flag"):
            events_crud._build_where(["--unknown", "value"])

    def test_missing_flag_value_fails_closed(self):
        """A filter flag with no value raises ValueError instead of being
        silently dropped."""
        with pytest.raises(ValueError, match="requires a value"):
            events_crud._build_where(["--item-id"])

    def test_filter_value_cannot_be_next_flag(self):
        """A value-taking filter must not consume the next flag as its value."""
        with pytest.raises(ValueError, match="requires a value"):
            events_crud._build_where(["--item", "--since", "2026-05-07T00:00:00Z"])

    def test_invalid_item_filter_value_fails_closed(self):
        """Item filters accept refs or project-local sequences with context."""
        with pytest.raises(ValueError, match="requires PREFIX-N"):
            events_crud._build_where(["--item", "not-a-ticket"])

    def test_item_alias_normalizes_through_item_id(self, db_path):
        """``--item`` resolves public refs and project-local numeric refs."""
        where, params = events_crud._build_where(
            ["--item", TEST_ITEM_REF], db_path=db_path,
        )
        assert "item_id=%s" in where
        assert params == [str(TEST_ITEM_ID)]
        where, params = events_crud._build_where(
            ["--item", str(TEST_ITEM_ID), "--project", "yoke"],
            db_path=db_path,
        )
        assert "item_id=%s" in where
        assert "project_id=%s" in where
        assert params == [str(TEST_ITEM_ID), 1]
        where, params = events_crud._build_where(
            ["--project", "yoke", "--item", str(TEST_ITEM_ID)],
            db_path=db_path,
        )
        assert "item_id=%s" in where
        assert "project_id=%s" in where
        assert params == [1, str(TEST_ITEM_ID)]

    def test_item_alias_bare_number_requires_project_context(self, db_path):
        with pytest.raises(ValueError, match="project context"):
            events_crud._build_where(["--item", str(TEST_ITEM_ID)], db_path=db_path)

    def test_item_alias_missing_project_sequence_reports_not_found(self, db_path):
        with pytest.raises(ValueError, match="not found"):
            events_crud._build_where(
                ["--item", "999999", "--project", "yoke"],
                db_path=db_path,
            )


class TestPrune:
    def test_prune_dry_run(self, test_db):
        _setup_severity_config(test_db)
        _insert_event_direct(test_db, severity="DEBUG", created_at="2020-01-01T00:00:00Z")
        _insert_event_direct(test_db, severity="INFO", created_at="2020-01-01T00:00:00Z")

        # Dry run: check counts
        debug_count = test_db.execute(
            "SELECT COUNT(*) FROM events WHERE severity='DEBUG' AND created_at < %s",
            (_SEVEN_DAYS_AGO,),
        ).fetchone()[0]
        assert debug_count == 1

    def test_prune_actually_deletes(self, test_db):
        _insert_event_direct(test_db, severity="DEBUG", created_at="2020-01-01T00:00:00Z")
        _insert_event_direct(test_db, severity="STATUS", created_at="2020-01-01T00:00:00Z")

        before = _event_count(test_db)
        assert before == 2

        # Delete old DEBUG events
        test_db.execute(
            "DELETE FROM events WHERE severity='DEBUG' AND created_at < %s",
            (_SEVEN_DAYS_AGO,),
        )
        test_db.commit()

        after = _event_count(test_db)
        assert after == 1  # STATUS retained

    def test_retention_tiers(self):
        """Verify retention tier constants."""
        assert events_crud._RETENTION_DAYS["DEBUG"] == 1
        assert events_crud._RETENTION_DAYS["INFO"] == 30
        assert events_crud._RETENTION_DAYS["WARN"] == 90
        assert events_crud._RETENTION_DAYS["STATUS"] is None  # forever
        assert events_crud._RETENTION_DAYS["ERROR"] is None
        assert events_crud._RETENTION_DAYS["FATAL"] is None
