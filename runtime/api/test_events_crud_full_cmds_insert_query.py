"""CLI/cmd tests: cmd_insert dedup + severity skip, cmd_list/count/tail/anomalies/query, cmd_prune."""

from __future__ import annotations

import pytest

from yoke_core.domain import events_crud
from runtime.api.events_crud_full_test_helpers import (  # noqa: F401
    _THIRTY_DAYS_AGO,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
    db_path,
)
from runtime.api.fixtures.file_test_db import connect_test_db


class TestCmdInsert:
    def test_insert_passes_severity_filter(self, db_path):
        events_crud.cmd_insert(
            db_path,
            event_id="evt-1",
            source_type="system",
            session_id="s1",
            event_kind="lifecycle",
            event_type="test",
            event_name="TestEvent",
            severity="WARN",
        )

        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        assert count == 1

    def test_insert_dropped_below_severity(self, db_path):
        events_crud.cmd_severity_config_set(db_path, "*", "*", "ERROR")

        events_crud.cmd_insert(
            db_path,
            event_id="evt-dropped",
            source_type="system",
            session_id="s1",
            event_kind="lifecycle",
            event_type="test",
            event_name="LowPri",
            severity="INFO",
        )

        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        assert count == 0  # dropped

    def test_insert_skip_severity(self, db_path):
        events_crud.cmd_severity_config_set(db_path, "*", "*", "ERROR")

        events_crud.cmd_insert(
            db_path,
            event_id="evt-forced",
            source_type="system",
            session_id="s1",
            event_kind="lifecycle",
            event_type="test",
            event_name="Forced",
            severity="DEBUG",
            skip_severity=True,
        )

        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        assert count == 1  # bypassed filter

    def test_insert_deduplication(self, db_path):
        for _ in range(3):
            events_crud.cmd_insert(
                db_path,
                event_id="evt-dup",
                source_type="system",
                session_id="s1",
                event_kind="lifecycle",
                event_type="test",
                event_name="DupEvent",
                skip_severity=True,
            )

        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        assert count == 1

    def test_insert_item_id_sun_prefix(self, db_path):
        events_crud.cmd_insert(
            db_path,
            event_id="evt-sun",
            source_type="system",
            session_id="s1",
            event_kind="lifecycle",
            event_type="test",
            event_name="ItemEvt",
            item_id=TEST_ITEM_REF,
            skip_severity=True,
        )

        conn = connect_test_db(db_path)
        row = conn.execute("SELECT item_id FROM events WHERE event_id='evt-sun'").fetchone()
        conn.close()
        assert row[0] == str(TEST_ITEM_ID)


class TestQueryCmds:
    def _populated_db(self, db_path) -> str:
        for i, (name, sev, flags) in enumerate([
            ("Alpha", "INFO", None),
            ("Beta", "WARN", "nonzero_exit"),
            ("Gamma", "ERROR", None),
        ]):
            events_crud.cmd_insert(
                db_path,
                event_id=f"evt-{i}",
                source_type="system",
                session_id="s1",
                event_kind="lifecycle",
                event_type="test",
                event_name=name,
                severity=sev,
                anomaly_flags=flags,
                skip_severity=True,
            )
        return db_path

    def test_list_all(self, db_path):
        self._populated_db(db_path)
        result = events_crud.cmd_list(db_path)
        lines = [l for l in result.split("\n") if l]
        assert len(lines) == 3

    def test_list_with_filter(self, db_path):
        self._populated_db(db_path)
        result = events_crud.cmd_list(db_path, ["--event-name", "Alpha"])
        assert "Alpha" in result
        assert "Beta" not in result

    def test_count_all(self, db_path):
        self._populated_db(db_path)
        assert events_crud.cmd_count(db_path) == 3

    def test_count_with_filter(self, db_path):
        self._populated_db(db_path)
        assert events_crud.cmd_count(db_path, ["--min-severity", "WARN"]) == 2

    def test_tail_default(self, db_path):
        self._populated_db(db_path)
        result = events_crud.cmd_tail(db_path, 2)
        lines = [l for l in result.split("\n") if l]
        assert len(lines) == 2

    def test_anomalies(self, db_path):
        self._populated_db(db_path)
        result = events_crud.cmd_anomalies(db_path)
        assert "nonzero_exit" in result
        lines = [l for l in result.split("\n") if l]
        assert len(lines) == 1

    def test_query_passthrough(self, db_path):
        self._populated_db(db_path)
        result = events_crud.cmd_query(db_path, "SELECT event_name FROM events ORDER BY event_name")
        assert "Alpha" in result

    def test_query_empty_sql_raises(self, db_path):
        with pytest.raises(ValueError, match="SQL query is required"):
            events_crud.cmd_query(db_path, "")


class TestPruneCmds:
    def test_dry_run_output(self, db_path):
        events_crud.cmd_insert(
            db_path, event_id="old-debug", source_type="system", session_id="s1",
            event_kind="lifecycle", event_type="test", event_name="Old",
            severity="DEBUG", skip_severity=True,
        )
        # Manually backdate
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE events SET created_at=%s WHERE event_id='old-debug'",
            (_THIRTY_DAYS_AGO,),
        )
        conn.commit()
        conn.close()

        result = events_crud.cmd_prune(db_path, dry_run=True)
        assert "Would prune" in result
        assert "DEBUG=1" in result

    def test_actual_prune(self, db_path):
        # cmd_prune emits a migration_audit fingerprint through the exception
        # pathway; the db_path fixture stages migration_audit alongside events.
        events_crud.cmd_insert(
            db_path, event_id="old-debug", source_type="system", session_id="s1",
            event_kind="lifecycle", event_type="test", event_name="Old",
            severity="DEBUG", skip_severity=True,
        )
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE events SET created_at=%s WHERE event_id='old-debug'",
            (_THIRTY_DAYS_AGO,),
        )
        conn.commit()
        conn.close()

        result = events_crud.cmd_prune(db_path, dry_run=False)
        assert "Pruned" in result
        assert "DEBUG=1" in result

        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        assert count == 0
