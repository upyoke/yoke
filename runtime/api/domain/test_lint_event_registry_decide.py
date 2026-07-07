"""lint_event_registry — decide() pure decision surface.

Split out of ``test_lint_event_registry.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import lint_event_registry as lint_mod
from yoke_core.domain.lint_event_registry import decide
from yoke_core.domain.lint_event_registry_test_helpers import (  # noqa: F401 — fixtures
    _payload,
    no_table_db,
    registry_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db


class TestDecide:
    def test_invalid_payload_allows(self, registry_db):
        assert decide("not json", registry_db).action == "allow"

    def test_empty_payload_allows(self, registry_db):
        assert decide("", registry_db).action == "allow"

    def test_non_emit_event_command_allows(self, registry_db):
        payload = _payload("echo hello")
        assert decide(payload, registry_db).action == "allow"

    def test_emit_event_help_allows(self, registry_db):
        payload = _payload("sh emit-event.sh --help")
        assert decide(payload, registry_db).action == "allow"

    def test_active_event_allows(self, registry_db):
        payload = _payload('sh emit-event.sh --name "ActiveEvent" --kind x')
        d = decide(payload, registry_db)
        assert d.action == "allow"
        assert d.event_name == "ActiveEvent"

    def test_active_event_unquoted_allows(self, registry_db):
        payload = _payload("sh emit-event.sh --name ActiveEvent --kind x")
        assert decide(payload, registry_db).action == "allow"

    def test_active_event_single_quoted_allows(self, registry_db):
        payload = _payload("sh emit-event.sh --name 'ActiveEvent' --kind x")
        assert decide(payload, registry_db).action == "allow"

    def test_deprecated_event_warns(self, registry_db):
        payload = _payload('sh emit-event.sh --name "DeprecatedEvent" --kind x')
        d = decide(payload, registry_db)
        assert d.action == "warn"
        assert "DeprecatedEvent" in d.stderr_message
        assert d.deny_json == ""

    def test_unregistered_event_denies(self, registry_db):
        payload = _payload('sh emit-event.sh --name "Unknown" --kind x')
        d = decide(payload, registry_db)
        assert d.action == "deny"
        assert d.event_name == "Unknown"
        assert '"permissionDecision": "deny"' in d.deny_json
        assert "Unknown" in d.reason
        assert "python3 -m yoke_core.cli.db_router events registry add" in d.reason

    def test_unregistered_event_full_path_denies(self, registry_db):
        payload = _payload('sh /abs/path/emit-event.sh --name "Unknown"')
        assert decide(payload, registry_db).action == "deny"

    def test_no_table_allows_gracefully(self, no_table_db):
        payload = _payload('sh emit-event.sh --name "Unknown" --kind x')
        assert decide(payload, no_table_db).action == "allow"

    def test_missing_db_allows_gracefully(self, tmp_path, monkeypatch):
        missing = str(tmp_path / "missing.db")
        payload = _payload('sh emit-event.sh --name "Unknown" --kind x')
        if db_backend.is_postgres():
            monkeypatch.setattr(
                lint_mod,
                "connect",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("no database")
                ),
            )
        assert decide(payload, missing).action == "allow"

    def test_custom_status_denies(self, registry_db):
        conn = connect_test_db(registry_db)
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, "
            f"owner_service, description, status) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            ("WeirdEvent", "lifecycle", "system", "core", "weird", "draft"),
        )
        conn.commit()
        conn.close()
        payload = _payload('sh emit-event.sh --name "WeirdEvent" --kind x')
        assert decide(payload, registry_db).action == "deny"

    @pytest.mark.parametrize("shape", ["tool_input", "toolInput", "input", "top_level"])
    def test_all_payload_shapes_deny_unregistered(self, registry_db, shape):
        payload = _payload('sh emit-event.sh --name "Unknown"', shape=shape)
        assert decide(payload, registry_db).action == "deny"

    def test_hook_meta_propagates(self, registry_db):
        payload = _payload(
            'sh emit-event.sh --name "Unknown"',
            session_id="sid-xyz",
            tool_use_id="tu-abc",
            turn_id="tr-123",
        )
        d = decide(payload, registry_db)
        assert d.hook_meta.session_id == "sid-xyz"
        assert d.hook_meta.tool_use_id == "tu-abc"
        assert d.hook_meta.turn_id == "tr-123"
