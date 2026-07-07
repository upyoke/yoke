"""Direct API tests: event_registry CRUD + discover-helper validation."""

from __future__ import annotations

from yoke_core.domain import events_crud


class TestRegistryCRUD:
    def _add_registry_entry(self, conn, name="TestEvent", kind="lifecycle",
                             event_type="test", service="cli", desc="Test event"):
        conn.execute(
            "INSERT INTO event_registry "
            "(event_name, event_kind, event_type, owner_service, description, severity_default, status) "
            "VALUES (%s, %s, %s, %s, %s, 'INFO', 'active') "
            "ON CONFLICT(event_name) DO NOTHING",
            (name, kind, event_type, service, desc),
        )
        conn.commit()

    def test_add_and_get(self, test_db):
        self._add_registry_entry(test_db, "MyEvent")
        row = test_db.execute(
            "SELECT * FROM event_registry WHERE event_name='MyEvent'"
        ).fetchone()
        assert row is not None
        assert row["event_kind"] == "lifecycle"
        assert row["status"] == "active"

    def test_get_not_found(self, test_db):
        row = test_db.execute(
            "SELECT * FROM event_registry WHERE event_name='Nonexistent'"
        ).fetchone()
        assert row is None

    def test_list_active_only(self, test_db):
        self._add_registry_entry(test_db, "Active1")
        self._add_registry_entry(test_db, "Active2")
        test_db.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, owner_service, description, status) "
            "VALUES ('Deprecated1', 'lifecycle', 'test', 'cli', 'Deprecated', 'deprecated')"
        )
        test_db.commit()

        active = test_db.execute(
            "SELECT * FROM event_registry WHERE status='active'"
        ).fetchall()
        assert len(active) == 2

    def test_list_all(self, test_db):
        self._add_registry_entry(test_db, "Active1")
        test_db.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, owner_service, description, status) "
            "VALUES ('Dep1', 'lifecycle', 'test', 'cli', 'Dep', 'deprecated')"
        )
        test_db.commit()

        all_rows = test_db.execute("SELECT * FROM event_registry").fetchall()
        assert len(all_rows) == 2

    def test_update_fields(self, test_db):
        self._add_registry_entry(test_db, "UpdEvent")
        test_db.execute(
            "UPDATE event_registry SET description='Updated desc' WHERE event_name='UpdEvent'"
        )
        test_db.commit()
        row = test_db.execute(
            "SELECT description FROM event_registry WHERE event_name='UpdEvent'"
        ).fetchone()
        assert row[0] == "Updated desc"

    def test_deprecate(self, test_db):
        self._add_registry_entry(test_db, "DepEvent")
        test_db.execute(
            "UPDATE event_registry SET status='deprecated' WHERE event_name='DepEvent'"
        )
        test_db.commit()
        row = test_db.execute(
            "SELECT status FROM event_registry WHERE event_name='DepEvent'"
        ).fetchone()
        assert row[0] == "deprecated"

    def test_delete(self, test_db):
        self._add_registry_entry(test_db, "DelEvent")
        test_db.execute("DELETE FROM event_registry WHERE event_name='DelEvent'")
        test_db.commit()
        count = test_db.execute(
            "SELECT COUNT(*) FROM event_registry WHERE event_name='DelEvent'"
        ).fetchone()[0]
        assert count == 0

    def test_count_all(self, test_db):
        self._add_registry_entry(test_db, "A")
        self._add_registry_entry(test_db, "B")
        self._add_registry_entry(test_db, "C")
        count = test_db.execute("SELECT COUNT(*) FROM event_registry").fetchone()[0]
        assert count == 3

    def test_count_by_status(self, test_db):
        self._add_registry_entry(test_db, "Active1")
        test_db.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, owner_service, description, status) "
            "VALUES ('Dep1', 'lifecycle', 'test', 'cli', 'Dep', 'deprecated')"
        )
        test_db.commit()

        active_count = test_db.execute(
            "SELECT COUNT(*) FROM event_registry WHERE status='active'"
        ).fetchone()[0]
        dep_count = test_db.execute(
            "SELECT COUNT(*) FROM event_registry WHERE status='deprecated'"
        ).fetchone()[0]
        assert active_count == 1
        assert dep_count == 1

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

    def test_native_conflict_dedup(self, test_db):
        self._add_registry_entry(test_db, "DupEvent")
        self._add_registry_entry(test_db, "DupEvent")
        count = test_db.execute(
            "SELECT COUNT(*) FROM event_registry WHERE event_name='DupEvent'"
        ).fetchone()[0]
        assert count == 1


class TestRegistryDiscover:
    def test_validate_event_name_pascal_case(self):
        assert events_crud._validate_event_name("TestEvent") is True
        assert events_crud._validate_event_name("A") is True
        assert events_crud._validate_event_name("ABCDef") is True

    def test_validate_event_name_rejects_lowercase_start(self):
        assert events_crud._validate_event_name("testEvent") is False

    def test_validate_event_name_rejects_empty(self):
        assert events_crud._validate_event_name("") is False

    def test_validate_event_name_rejects_special_chars(self):
        assert events_crud._validate_event_name("Test-Event") is False
        assert events_crud._validate_event_name("Test_Event") is False

    def test_extract_event_name_from_line(self):
        assert events_crud._extract_event_name_from_line('--name "TestEvent"') == "TestEvent"
        assert events_crud._extract_event_name_from_line("--name 'TestEvent'") == "TestEvent"
        assert events_crud._extract_event_name_from_line("--name TestEvent") == "TestEvent"
        assert events_crud._extract_event_name_from_line("no name here") is None
        assert events_crud._extract_event_name_from_line('--name "invalid-name"') is None

    def test_join_continuation_lines(self):
        text = "line1 \\\nline2 \\\nline3\nline4"
        result = events_crud._join_continuation_lines(text)
        assert len(result) == 2
        assert "line1" in result[0]
        assert "line2" in result[0]
        assert "line3" in result[0]
        assert result[1] == "line4"
