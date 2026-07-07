"""AC-8.1 dispatcher-parity tests for the structured-field write CLI.

Companion to :mod:`test_service_client_delivery_exec_update`. Verifies
that ``items update YOK-N <field> --stdin|--body-file`` routes through
:func:`yoke_core.domain.yoke_function_dispatch.dispatch` for
``items.structured_field.replace`` rather than calling the domain
helper directly.

Each test patches the handler's import of ``execute_structured_write``
plus ``_read_field`` so the assertion sees the dispatcher hop, and
silences ``verify_claim`` because the fake DB has no harness_sessions
rows.
"""

from __future__ import annotations

import io
import json
import sys


class TestCmdExecuteUpdateCliDispatchParity:
    """AC-8.1 — structured-field write routes through the function dispatcher."""

    def test_routes_body_file_through_dispatcher(self, monkeypatch, capsys, tmp_path):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import yoke_function_dispatch as dispatch_module
        from yoke_core.domain.handlers import items_structured_field

        spec_path = tmp_path / "spec.md"
        spec_path.write_text("# Spec\n", encoding="utf-8")

        called: dict = {}

        def _record_structured_write(**kwargs):
            called.update(kwargs)
            return {"success": True}

        monkeypatch.setattr(
            items_structured_field, "execute_structured_write",
            _record_structured_write,
        )
        monkeypatch.setattr(
            items_structured_field, "_read_field", lambda *a, **kw: "# Spec\n",
        )
        monkeypatch.setattr(
            dispatch_module, "verify_claim", lambda *a, **kw: None,
        )

        rc = service_client.cmd_execute_update_cli(
            ["1", "spec", "--body-file", str(spec_path), "--force", "--source", "tester"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0, captured
        assert data["success"] is True
        # The handler is called with content (the CLI reads the file
        # before dispatch) rather than file_path:
        assert called["item_id"] == 1
        assert called["field"] == "spec"
        assert called["content"] == "# Spec\n"
        assert called["force"] is True
        assert called["source"] == "tester"

    def test_routes_stdin_through_dispatcher(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import yoke_function_dispatch as dispatch_module
        from yoke_core.domain.handlers import items_structured_field

        called: dict = {}

        def _record_structured_write(**kwargs):
            called.update(kwargs)
            return {"success": True}

        monkeypatch.setattr(
            items_structured_field, "execute_structured_write",
            _record_structured_write,
        )
        monkeypatch.setattr(
            items_structured_field, "_read_field", lambda *a, **kw: "# Spec\n",
        )
        monkeypatch.setattr(
            dispatch_module, "verify_claim", lambda *a, **kw: None,
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO("# Spec\n"))

        rc = service_client.cmd_execute_update_cli(
            ["1", "spec", "--stdin", "--force", "--source", "tester"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0, captured
        assert data["success"] is True
        assert called["item_id"] == 1
        assert called["field"] == "spec"
        assert called["content"] == "# Spec\n"
        assert "file_path" not in called
        assert called["force"] is True
        assert called["source"] == "tester"

    def test_json_mode_emits_function_call_response_envelope(self, monkeypatch, capsys):
        """AC-8.5 — ``--json`` mode emits the FunctionCallResponse verbatim."""
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import yoke_function_dispatch as dispatch_module
        from yoke_core.domain.handlers import items_structured_field

        monkeypatch.setattr(
            items_structured_field, "execute_structured_write",
            lambda **kwargs: {"success": True},
        )
        monkeypatch.setattr(
            items_structured_field, "_read_field", lambda *a, **kw: "x\n",
        )
        monkeypatch.setattr(
            dispatch_module, "verify_claim", lambda *a, **kw: None,
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO("x\n"))

        rc = service_client.cmd_execute_update_cli(
            ["1", "spec", "--stdin", "--json"]
        )

        captured = capsys.readouterr()
        envelope = json.loads(captured.out)
        assert rc == 0, captured
        # Typed envelope shape (FunctionCallResponse):
        assert envelope["success"] is True
        assert envelope["function"] == "items.structured_field.replace"
        assert "result" in envelope
        # Result payload matches the ReplaceResponse pydantic model:
        result = envelope["result"]
        for key in (
            "item_id", "field", "old_line_count", "new_line_count",
            "old_hash", "new_hash", "payload_byte_count", "verification",
            "github_sync",
        ):
            assert key in result, f"missing key {key!r} in {result!r}"
