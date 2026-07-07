"""Direct Python tests for ``yoke_core.domain.lint_event_registry``.

Original module covered every flavor of the lint hook. It is now split across
sibling files so each authored file stays under the 350-line limit:
``decide()`` cases live in ``test_lint_event_registry_decide``, and
``emit_denial`` / ``run`` / canonical-fallback cases live in
``test_lint_event_registry_run``. This file covers the small parsing and
render-helper surfaces.
"""

from __future__ import annotations

import json

from yoke_core.domain import db_backend
from yoke_core.domain import lint_event_registry as lint_mod
from yoke_core.domain.lint_event_registry import (
    HookMeta,
    build_deny_json,
    build_deny_reason,
    build_deprecated_warning,
    extract_command,
    extract_event_name,
    extract_hook_meta,
    lookup_event_status,
    parse_payload,
)
from yoke_core.domain.lint_event_registry_test_helpers import (  # noqa: F401 — fixtures
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


class TestExtractHookMeta:
    def test_all_fields_present(self):
        meta = extract_hook_meta(
            {"session_id": "s1", "tool_use_id": "t1", "turn_id": "tr1"}
        )
        assert meta == HookMeta(session_id="s1", tool_use_id="t1", turn_id="tr1")

    def test_turn_id_falls_back_to_message_id(self):
        meta = extract_hook_meta({"session_id": "s1", "message_id": "m1"})
        assert meta.turn_id == "m1"

    def test_missing_fields_become_empty_strings(self):
        meta = extract_hook_meta({})
        assert meta.session_id == ""
        assert meta.tool_use_id == ""
        assert meta.turn_id == ""

    def test_non_dict_returns_empty_meta(self):
        assert extract_hook_meta(None) == HookMeta()  # type: ignore[arg-type]


class TestLookupEventStatus:
    def test_missing_db_path(self, monkeypatch):
        if db_backend.is_postgres():
            monkeypatch.setattr(
                lint_mod,
                "connect",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("no database")
                ),
            )
        assert lookup_event_status("", "Foo") == (False, None)

    def test_nonexistent_db_file(self, tmp_path, monkeypatch):
        missing = str(tmp_path / "missing.db")
        if db_backend.is_postgres():
            monkeypatch.setattr(
                lint_mod,
                "connect",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("no database")
                ),
            )
        assert lookup_event_status(missing, "Foo") == (False, None)

    def test_missing_table(self, no_table_db):
        assert lookup_event_status(no_table_db, "Foo") == (False, None)

    def test_active_event(self, registry_db):
        assert lookup_event_status(registry_db, "ActiveEvent") == (True, "active")

    def test_deprecated_event(self, registry_db):
        assert lookup_event_status(registry_db, "DeprecatedEvent") == (
            True,
            "deprecated",
        )

    def test_unknown_event(self, registry_db):
        assert lookup_event_status(registry_db, "Unknown") == (True, None)


class TestBuildDenyReason:
    def test_contains_event_name(self):
        reason = build_deny_reason("Foo")
        assert "Foo" in reason

    def test_contains_registration_command(self):
        reason = build_deny_reason("Foo")
        assert "python3 -m yoke_core.cli.db_router events registry add" in reason


class TestBuildDenyJson:
    def test_parseable_and_contains_deny(self):
        raw = build_deny_json("Foo")
        # The shell test suite greps for this exact substring.
        assert '"permissionDecision": "deny"' in raw
        payload = json.loads(raw)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "Foo" in payload["hookSpecificOutput"]["permissionDecisionReason"]


class TestBuildDeprecatedWarning:
    def test_contains_event_name(self):
        warn = build_deprecated_warning("Foo")
        assert "Foo" in warn
        assert "deprecated" in warn
        assert warn.startswith("WARN")
