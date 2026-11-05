"""Direct API tests: event_registry table shape + discover-helper validation."""

from __future__ import annotations

import pytest

from yoke_core.domain import events_crud


class TestRegistryTable:
    @pytest.fixture(autouse=True)
    def _empty_registry(self, test_db):
        """Keep direct counts independent of the catalog-projected rows."""
        test_db.execute("DELETE FROM event_registry")
        test_db.commit()

    def _add_registry_entry(
        self,
        conn,
        name="TestEvent",
        kind="lifecycle",
        event_type="test",
        service="cli",
        desc="Test event",
    ):
        conn.execute(
            "INSERT INTO event_registry "
            "(event_name, event_kind, event_type, owner_service, description) "
            "VALUES (%s, %s, %s, %s, %s)",
            (name, kind, event_type, service, desc),
        )
        conn.commit()

    def test_columns_match_catalog_projection(self, test_db):
        rows = test_db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'event_registry'"
        ).fetchall()
        assert {row[0] for row in rows} == {
            "event_name",
            "event_kind",
            "event_type",
            "owner_service",
            "description",
            "severity_default",
        }

    def test_add_and_get(self, test_db):
        self._add_registry_entry(test_db, "MyEvent")
        row = test_db.execute(
            "SELECT * FROM event_registry WHERE event_name='MyEvent'"
        ).fetchone()
        assert row is not None
        assert row["event_kind"] == "lifecycle"
        assert row["severity_default"] == "INFO"

    def test_get_not_found(self, test_db):
        row = test_db.execute(
            "SELECT * FROM event_registry WHERE event_name='Nonexistent'"
        ).fetchone()
        assert row is None

    def test_list_all(self, test_db):
        self._add_registry_entry(test_db, "First1")
        self._add_registry_entry(test_db, "Second1")

        all_rows = test_db.execute("SELECT * FROM event_registry").fetchall()
        assert len(all_rows) == 2

    def test_count_all(self, test_db):
        self._add_registry_entry(test_db, "A")
        self._add_registry_entry(test_db, "B")
        self._add_registry_entry(test_db, "C")
        count = test_db.execute("SELECT COUNT(*) FROM event_registry").fetchone()[0]
        assert count == 3

    def test_filter_by_kind(self, test_db):
        self._add_registry_entry(test_db, "Life1", kind="lifecycle")
        self._add_registry_entry(test_db, "Tel1", kind="telemetry")

        life = test_db.execute(
            "SELECT * FROM event_registry WHERE event_kind='lifecycle'"
        ).fetchall()
        assert len(life) == 1
        assert life[0]["event_name"] == "Life1"

    def test_filter_by_service(self, test_db):
        self._add_registry_entry(test_db, "Cli1", service="cli")
        self._add_registry_entry(test_db, "Hook1", service="hooks")

        hooks = test_db.execute(
            "SELECT * FROM event_registry WHERE owner_service='hooks'"
        ).fetchall()
        assert len(hooks) == 1


class TestRegistryDiscover:


    def test_extract_event_name_from_line(self):
        assert (
            events_crud._extract_event_name_from_line('--name "TestEvent"')
            == "TestEvent"
        )
        assert (
            events_crud._extract_event_name_from_line("--name 'TestEvent'")
            == "TestEvent"
        )
        assert (
            events_crud._extract_event_name_from_line("--name TestEvent") == "TestEvent"
        )
        assert events_crud._extract_event_name_from_line("no name here") is None
        assert (
            events_crud._extract_event_name_from_line('--name "invalid-name"') is None
        )

    def test_join_continuation_lines(self):
        text = "line1 \\\nline2 \\\nline3\nline4"
        result = events_crud._join_continuation_lines(text)
        assert len(result) == 2
        assert "line1" in result[0]
        assert "line2" in result[0]
        assert "line3" in result[0]
        assert result[1] == "line4"
