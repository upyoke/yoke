# ruff: noqa: F811

"""Direct Python tests for ``yoke_core.domain.lint_event_registry``.

Original module covered every flavor of the lint hook. It is now split across
sibling files so each authored file stays under the 350-line limit:
``decide()`` cases live in ``test_lint_event_registry_decide``, and
``evaluate`` / ``main`` / canonical-fallback cases live in
``test_lint_event_registry_run``. This file covers the small parsing and
render-helper surfaces.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain import lint_event_registry as lint_mod
from yoke_core.domain.lint_event_registry import (
    build_deny_reason,
    extract_command,
    extract_event_name,
    lookup_event_registered,
    parse_payload,
)
from runtime.api.domain.lint_event_registry_test_helpers import (  # noqa: F401 — fixtures
    no_table_db,
    registry_db,
)


class TestParsePayload:
    def test_empty_string_returns_none(self):
        assert parse_payload("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_payload("   \n\n  ") is None

    def test_invalid_json_returns_none(self):
        assert parse_payload("not json") is None

    def test_top_level_array_returns_none(self):
        # Non-dict roots are treated as unparseable by the hook.
        assert parse_payload("[1,2,3]") is None

    def test_valid_dict_returns_dict(self):
        data = parse_payload('{"a": 1}')
        assert data == {"a": 1}


class TestExtractCommand:
    def test_tool_input_command(self):
        assert extract_command({"tool_input": {"command": "ls"}}) == "ls"

    def test_camelcase_toolInput_command(self):
        assert extract_command({"toolInput": {"command": "ls"}}) == "ls"

    def test_bare_input_command(self):
        assert extract_command({"input": {"command": "ls"}}) == "ls"

    def test_cmd_fallback(self):
        assert extract_command({"tool_input": {"cmd": "ls"}}) == "ls"

    def test_top_level_command(self):
        assert extract_command({"command": "ls"}) == "ls"

    def test_missing_returns_empty(self):
        assert extract_command({}) == ""

    def test_non_dict_tool_input_returns_empty(self):
        assert extract_command({"tool_input": "not a dict"}) == ""


class TestExtractEventName:
    def test_double_quoted(self):
        cmd = 'sh emit-event.sh --name "MyEvent" --kind lifecycle'
        assert extract_event_name(cmd) == "MyEvent"

    def test_single_quoted(self):
        cmd = "sh emit-event.sh --name 'MyEvent' --kind lifecycle"
        assert extract_event_name(cmd) == "MyEvent"

    def test_unquoted(self):
        cmd = "sh emit-event.sh --name MyEvent --kind lifecycle"
        assert extract_event_name(cmd) == "MyEvent"

    def test_extra_whitespace(self):
        cmd = 'sh emit-event.sh --name   "MyEvent"  --kind lifecycle'
        assert extract_event_name(cmd) == "MyEvent"

    def test_no_name_returns_none(self):
        assert extract_event_name("sh emit-event.sh --help") is None

    def test_empty_command_returns_none(self):
        assert extract_event_name("") is None

    def test_non_string_command_returns_none(self):
        assert extract_event_name(None) is None  # type: ignore[arg-type]


class TestLookupEventRegistered:
    def test_missing_db_path(self, monkeypatch):
        if db_backend.is_postgres():
            monkeypatch.setattr(
                lint_mod,
                "connect",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("no database")
                ),
            )
        assert lookup_event_registered("", "Foo") == (False, False)

    def test_missing_table(self, no_table_db):
        assert lookup_event_registered(no_table_db, "Foo") == (False, False)

    def test_registered_event(self, registry_db):
        assert lookup_event_registered(registry_db, "RegisteredEvent") == (True, True)

    def test_unknown_event(self, registry_db):
        assert lookup_event_registered(registry_db, "Unknown") == (True, False)


class TestBuildDenyReason:
    def test_contains_event_name(self):
        reason = build_deny_reason("Foo")
        assert "Foo" in reason

    def test_teaches_the_catalog_registration_path(self):
        reason = build_deny_reason("Foo")
        assert "event_catalog.py" in reason
        assert "python3 -m yoke_core.domain.event_catalog_render" in reason
