"""Tests for yoke_core.domain.events_crud — init, insert, queries,
severity config, and event-name validation."""

from __future__ import annotations

import pytest

from yoke_core.domain import events_crud as ec
from yoke_core.domain.schema_common import _table_exists
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.events_crud_test_fixtures import (
    _insert_event,
)


pytest_plugins = ("runtime.api.events_crud_test_fixtures",)


class TestInit:
    def test_init_creates_tables(self, db_path: str) -> None:
        conn = connect_test_db(db_path)
        try:
            assert _table_exists(conn, "events")
            assert _table_exists(conn, "severity_config")
            assert _table_exists(conn, "event_registry")
        finally:
            conn.close()

    def test_init_idempotent(self, db_path: str) -> None:
        """Running init twice should not error."""
        ec.cmd_init(db_path)  # second call
        ec.cmd_init(db_path)  # third call

    def test_init_seeds_catch_all_severity(self, db_path: str) -> None:
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT min_severity FROM severity_config "
            "WHERE event_name='*' AND source_type='*'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "INFO"


class TestInsert:
    def test_basic_insert(self, db_path: str) -> None:
        _insert_event(db_path, event_id="ins-001")
        count = ec.cmd_count(db_path)
        assert count == 1

    def test_dedup_on_event_id(self, db_path: str) -> None:
        _insert_event(db_path, event_id="dup-001")
        _insert_event(db_path, event_id="dup-001")
        count = ec.cmd_count(db_path)
        assert count == 1

    def test_invalid_source_type(self, db_path: str) -> None:
        with pytest.raises(ValueError, match="source_type"):
            ec.cmd_insert(
                db_path,
                event_id="bad-src",
                source_type="invalid",
                session_id="s1",
                event_kind="k",
                event_type="t",
                event_name="Foo",
                skip_severity=True,
            )

    def test_invalid_severity(self, db_path: str) -> None:
        with pytest.raises(ValueError, match="severity"):
            ec.cmd_insert(
                db_path,
                event_id="bad-sev",
                source_type="agent",
                session_id="s1",
                event_kind="k",
                event_type="t",
                event_name="Foo",
                severity="INVALID",
                skip_severity=True,
            )

    def test_item_id_persists_as_numeric_format(self, db_path: str) -> None:
        _insert_event(db_path, event_id="sun-strip", item_id="42")
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT item_id FROM events WHERE event_id='sun-strip'"
        ).fetchone()
        conn.close()
        assert row[0] == "42"

    def test_severity_filter_drops(self, db_path: str) -> None:
        """Events below severity threshold are silently dropped."""
        # Set threshold to WARN
        ec.cmd_severity_config_set(db_path, "*", "*", "WARN")
        ec.cmd_insert(
            db_path,
            event_id="dropped-debug",
            source_type="agent",
            session_id="s1",
            event_kind="k",
            event_type="t",
            event_name="LowPriority",
            severity="DEBUG",
        )
        count = ec.cmd_count(db_path)
        assert count == 0

    def test_skip_severity_bypasses_filter(self, db_path: str) -> None:
        ec.cmd_severity_config_set(db_path, "*", "*", "WARN")
        ec.cmd_insert(
            db_path,
            event_id="forced-debug",
            source_type="agent",
            session_id="s1",
            event_kind="k",
            event_type="t",
            event_name="ForcedEvent",
            severity="DEBUG",
            skip_severity=True,
        )
        count = ec.cmd_count(db_path)
        assert count == 1

    def test_optional_fields(self, db_path: str) -> None:
        _insert_event(
            db_path,
            event_id="opt-fields",
            event_outcome="completed",
            agent="engineer",
            tool_name="Bash",
            duration_ms=150,
            exit_code=0,
            envelope='{"event_name":"HarnessToolCallCompleted"}',
        )
        result = ec.cmd_list(db_path)
        assert "opt-fields" in result
        assert "engineer" in result


class TestQueries:
    def test_list_format(self, db_path: str) -> None:
        """Pipe-delimited format."""
        _insert_event(db_path, event_id="fmt-001", event_name="TestEvent")
        result = ec.cmd_list(db_path)
        assert "|" in result
        parts = result.split("|")
        assert len(parts) == 23  # 23 columns in _EVT_SELECT_COLS

    def test_list_filters(self, db_path: str) -> None:
        _insert_event(db_path, event_id="f-agent", source_type="agent")
        _insert_event(db_path, event_id="f-hook", source_type="hook")
        result = ec.cmd_list(db_path, ["--source-type", "hook"])
        assert "f-hook" in result
        assert "f-agent" not in result

    def test_count_with_filter(self, db_path: str) -> None:
        _insert_event(db_path, event_id="c-1", source_type="agent")
        _insert_event(db_path, event_id="c-2", source_type="hook")
        assert ec.cmd_count(db_path, ["--source-type", "agent"]) == 1

    def test_tail_default(self, db_path: str) -> None:
        for i in range(25):
            _insert_event(db_path, event_id=f"tail-{i:03d}")
        result = ec.cmd_tail(db_path, 5)
        lines = result.strip().split("\n")
        assert len(lines) == 5

    def test_anomalies(self, db_path: str) -> None:
        _insert_event(db_path, event_id="anom-1", anomaly_flags="nonzero_exit")
        _insert_event(db_path, event_id="anom-2")
        result = ec.cmd_anomalies(db_path)
        assert "anom-1" in result
        assert "anom-2" not in result

    def test_query_passthrough(self, db_path: str) -> None:
        _insert_event(db_path, event_id="q-1")
        result = ec.cmd_query(db_path, "SELECT COUNT(*) FROM events")
        assert "1" in result


class TestSeverityConfig:
    def test_set_and_list(self, db_path: str) -> None:
        result = ec.cmd_severity_config_set(db_path, "TestEvent", "agent", "WARN")
        assert "WARN" in result
        listing = ec.cmd_severity_config_list(db_path)
        assert "TestEvent" in listing

    def test_severity_check(self, db_path: str) -> None:
        ec.cmd_severity_config_set(db_path, "*", "*", "WARN")
        assert ec.cmd_severity_check(db_path, "Any", "agent", "ERROR") == "PASS"
        assert ec.cmd_severity_check(db_path, "Any", "agent", "DEBUG") == "DROP"


class TestValidateEventName:
    def test_valid_names(self) -> None:
        assert ec._validate_event_name("HarnessToolCallCompleted") is True
        assert ec._validate_event_name("A") is True
        assert ec._validate_event_name("Test123") is True

    def test_invalid_names(self) -> None:
        assert ec._validate_event_name("") is False
        assert ec._validate_event_name("lowercase") is False
        assert ec._validate_event_name("Has-Dash") is False
        assert ec._validate_event_name("has_underscore") is False
