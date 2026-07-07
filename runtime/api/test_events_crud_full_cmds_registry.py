"""CLI/cmd tests: event_registry add/get/list/update/deprecate/delete/count."""

from __future__ import annotations

import pytest

from yoke_core.domain import events_crud
from runtime.api.events_crud_full_test_helpers import db_path  # noqa: F401
from runtime.api.fixtures.file_test_db import connect_test_db


class TestRegistryCmds:
    def test_add_and_get(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="TestEvt", kind="lifecycle", event_type="test",
            service="cli", description="Test event"
        )
        result = events_crud.cmd_registry_get(db_path, "TestEvt")
        assert "TestEvt" in result
        assert "lifecycle" in result

    def test_add_with_context_schema(self, db_path):
        # ported from test-event-registry.sh A.11 — verify the
        # context_schema JSON payload round-trips through cmd_registry_add.
        schema_json = '{"tool_name": "string"}'
        events_crud.cmd_registry_add(
            db_path, name="WithSchema", kind="system", event_type="test",
            service="cli", description="Event with schema",
            context_schema=schema_json,
        )
        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT context_schema FROM event_registry WHERE event_name='WithSchema'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == schema_json

    def test_get_not_found(self, db_path):
        with pytest.raises(LookupError, match="not found"):
            events_crud.cmd_registry_get(db_path, "Missing")

    def test_list(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="A", kind="lifecycle", event_type="t",
            service="cli", description="a"
        )
        events_crud.cmd_registry_add(
            db_path, name="B", kind="lifecycle", event_type="t",
            service="cli", description="b"
        )
        result = events_crud.cmd_registry_list(db_path)
        assert "A" in result
        assert "B" in result

    def test_list_with_status_filter(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="Active1", kind="lifecycle", event_type="t",
            service="cli", description="a"
        )
        events_crud.cmd_registry_deprecate(db_path, "Active1")

        active_list = events_crud.cmd_registry_list(db_path, status="active")
        assert "Active1" not in active_list

        dep_list = events_crud.cmd_registry_list(db_path, status="deprecated")
        assert "Active1" in dep_list

    def test_update(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="UpdEvt", kind="lifecycle", event_type="t",
            service="cli", description="original"
        )
        events_crud.cmd_registry_update(db_path, "UpdEvt", description="updated")

        result = events_crud.cmd_registry_get(db_path, "UpdEvt")
        assert "updated" in result

    def test_update_not_found(self, db_path):
        with pytest.raises(LookupError):
            events_crud.cmd_registry_update(db_path, "Missing", description="x")

    def test_update_no_fields(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="Evt", kind="lifecycle", event_type="t",
            service="cli", description="d"
        )
        with pytest.raises(ValueError, match="no fields to update"):
            events_crud.cmd_registry_update(db_path, "Evt")

    def test_deprecate(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="DepEvt", kind="lifecycle", event_type="t",
            service="cli", description="d"
        )
        events_crud.cmd_registry_deprecate(db_path, "DepEvt")

        result = events_crud.cmd_registry_get(db_path, "DepEvt")
        assert "deprecated" in result

    def test_deprecate_not_found(self, db_path):
        with pytest.raises(LookupError):
            events_crud.cmd_registry_deprecate(db_path, "Missing")

    def test_delete(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="DelEvt", kind="lifecycle", event_type="t",
            service="cli", description="d"
        )
        events_crud.cmd_registry_delete(db_path, "DelEvt")

        with pytest.raises(LookupError):
            events_crud.cmd_registry_get(db_path, "DelEvt")

    def test_delete_not_found(self, db_path):
        with pytest.raises(LookupError):
            events_crud.cmd_registry_delete(db_path, "Missing")

    def test_count(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="A", kind="l", event_type="t", service="s", description="d"
        )
        events_crud.cmd_registry_add(
            db_path, name="B", kind="l", event_type="t", service="s", description="d"
        )
        assert events_crud.cmd_registry_count(db_path) == 2
        assert events_crud.cmd_registry_count(db_path, "active") == 2
        assert events_crud.cmd_registry_count(db_path, "deprecated") == 0

    def test_add_idempotent(self, db_path):
        events_crud.cmd_registry_add(
            db_path, name="Evt", kind="l", event_type="t", service="s", description="d"
        )
        events_crud.cmd_registry_add(
            db_path, name="Evt", kind="l", event_type="t", service="s", description="d"
        )
        assert events_crud.cmd_registry_count(db_path) == 1
