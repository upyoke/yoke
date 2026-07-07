"""CLI/cmd tests: cmd_init schema bootstrap + severity_config CLI surface."""

from __future__ import annotations

from yoke_core.domain import events_crud
from yoke_core.domain.schema_common import _table_exists
from runtime.api.events_crud_full_test_helpers import db_path  # noqa: F401
from runtime.api.fixtures.file_test_db import connect_test_db


class TestCmdInit:
    def test_init_creates_tables(self, db_path):
        # The db_path fixture applies events_crud.cmd_init; assert the tables.
        conn = connect_test_db(db_path)

        try:
            assert _table_exists(conn, "events")
            assert _table_exists(conn, "severity_config")
            assert _table_exists(conn, "event_registry")

            # Default severity config inserted
            default = conn.execute(
                "SELECT min_severity FROM severity_config WHERE event_name='*' AND source_type='*'"
            ).fetchone()
            assert default[0] == "INFO"
        finally:
            conn.close()

    def test_init_idempotent(self, db_path):
        # Fixture applies cmd_init once; calling it again must not raise or
        # duplicate the default severity_config row.
        events_crud.cmd_init(db_path)

        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM severity_config").fetchone()[0]
        assert count == 1  # Only one default row
        conn.close()


class TestSeverityConfigCmds:
    def test_set_and_list(self, db_path):
        result = events_crud.cmd_severity_config_set(db_path, "TestEvt", "agent", "WARN")
        assert "TestEvt" in result
        assert "WARN" in result

        listing = events_crud.cmd_severity_config_list(db_path)
        assert "TestEvt" in listing

    def test_check_severity_pass(self, db_path):
        # Default is INFO, so WARN should pass
        assert events_crud.check_severity(db_path, "AnyEvent", "system", "WARN") is True

    def test_check_severity_drop(self, db_path):
        # Set minimum to ERROR for specific event
        events_crud.cmd_severity_config_set(db_path, "StrictEvent", "*", "ERROR")
        # INFO should be dropped
        assert events_crud.check_severity(db_path, "StrictEvent", "system", "INFO") is False
        # ERROR should pass
        assert events_crud.check_severity(db_path, "StrictEvent", "system", "ERROR") is True

    def test_cmd_severity_check_output(self, db_path):
        assert events_crud.cmd_severity_check(db_path, "Any", "system", "WARN") == "PASS"

    def test_specific_source_type_match(self, db_path):
        events_crud.cmd_severity_config_set(db_path, "Evt", "agent", "ERROR")
        # agent source with INFO -> dropped
        assert events_crud.check_severity(db_path, "Evt", "agent", "INFO") is False
        # system source falls through to default INFO -> passes
        assert events_crud.check_severity(db_path, "Evt", "system", "INFO") is True
