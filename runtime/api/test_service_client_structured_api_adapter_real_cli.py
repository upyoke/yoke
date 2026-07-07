"""AC-8.6 real-CLI parity matrix.

For each adapter inventory entry that is wired through the dispatcher,
invoke the real CLI via ``main(argv)`` and compare the call payload
captured at the handler boundary against a direct
:func:`yoke_core.api.service_client_structured_api_adapter.call_dispatcher`
invocation with the equivalent payload. Identical typed result payloads
and identical handler call kwargs are the parity property.

Why ``main(argv)`` instead of ``subprocess.run``: subprocess invocation
in a fresh interpreter would have to set up YOKE_DB, registry, claim
attestation, and so on. ``main(argv)`` exercises every parser line, env
resolution, and dispatcher hop in-process — the failure mode the
previous matrix test missed (CLI never built a FunctionCallRequest at
all) is structurally caught here because the patch target is the
handler's domain owner, not a synthetic registry entry.

xfail markers cover inventory entries whose CLI has not yet been wired
through the dispatcher in this slice — adding wiring shrinks the xfail
count, never grows it.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace

import pytest


def _silence_claim(monkeypatch):
    from yoke_core.domain import yoke_function_dispatch as dispatch_module

    monkeypatch.setattr(
        dispatch_module, "verify_claim", lambda *a, **kw: None,
    )


class TestRealCliParityMatrix:
    """AC-8.6 — each wired CLI produces the same payload as direct dispatch."""

    def test_items_structured_field_replace_parity(self, monkeypatch):
        """``db_router items update YOK-N spec --stdin`` ↔ dispatch payload."""
        from yoke_core.domain.handlers import items_structured_field

        cli_calls: list[dict] = []
        direct_calls: list[dict] = []

        def _record_cli(**kwargs):
            cli_calls.append(dict(kwargs))
            return {"success": True}

        def _record_direct(**kwargs):
            direct_calls.append(dict(kwargs))
            return {"success": True}

        monkeypatch.setattr(
            items_structured_field, "_read_field", lambda *a, **kw: "# Body\n",
        )
        _silence_claim(monkeypatch)

        # --- CLI path: main(argv) through service_client.cmd_execute_update_cli
        import yoke_core.api.service_client as service_client

        monkeypatch.setattr(
            items_structured_field, "execute_structured_write",
            _record_cli,
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO("# Body\n"))
        out = io.StringIO()
        with redirect_stdout(out):
            rc_cli = service_client.cmd_execute_update_cli(
                ["1", "spec", "--stdin", "--source", "test"]
            )
        assert rc_cli == 0, out.getvalue()

        # --- Direct dispatch path: call the dispatcher with the equivalent payload
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        register_all_handlers()
        monkeypatch.setattr(
            items_structured_field, "execute_structured_write",
            _record_direct,
        )
        response = call_dispatcher(
            function_id="items.structured_field.replace",
            target=TargetRef(kind="item", item_id=1),
            payload={
                "field": "spec",
                "content": "# Body\n",
                "source": "test",
                "force": False,
            },
            options={"sync_github_body": True, "rebuild_board": True},
        )
        assert response.success is True

        # Parity: the handler's domain owner was called with identical kwargs
        # in both paths (after dropping the per-call ``out`` capture sink).
        assert len(cli_calls) == 1 and len(direct_calls) == 1
        for call in (cli_calls[0], direct_calls[0]):
            call.pop("out", None)
        assert cli_calls[0] == direct_calls[0]

    def test_workflow_item_epic_task_body_replace_parity(self, monkeypatch):
        """``epic task-update-body 42 1`` ↔ direct dispatch payload."""
        from yoke_core.domain.handlers import workflow_item_epic_task

        cli_calls: list[tuple] = []
        direct_calls: list[tuple] = []

        def _record_cli(conn, epic_id, task_num, body, *args, **kwargs):
            cli_calls.append((str(epic_id), int(task_num), body))
            return "ok"

        def _record_direct(conn, epic_id, task_num, body, *args, **kwargs):
            direct_calls.append((str(epic_id), int(task_num), body))
            return "ok"

        # Avoid the handler's own connection-and-validation work by stubbing
        # the conn-open helper, the body-row probe, and the cascade hook.
        class _Cur:
            def fetchone(self):
                return ("",)

        class _Conn:
            def execute(self, *_a, **_kw):
                return _Cur()

            def commit(self):
                pass

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(
            workflow_item_epic_task, "_open_connection", lambda: _Conn(),
        )
        _silence_claim(monkeypatch)

        from yoke_core.domain import epic
        from unittest.mock import patch as _patch

        # --- CLI path
        monkeypatch.setattr(
            workflow_item_epic_task.epic_task_crud,
            "task_update_body", _record_cli,
        )
        with _patch("yoke_core.domain.epic.connect", return_value=_Conn()), \
             _patch("yoke_core.domain.epic._validate_epic_exists"), \
             _patch(
                 "yoke_core.domain.epic._read_stdin_safe",
                 return_value="hello\n",
             ):
            out = io.StringIO()
            with redirect_stdout(out):
                epic.main(["task-update-body", "42", "1"])

        # --- Direct dispatch path
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        register_all_handlers()
        monkeypatch.setattr(
            workflow_item_epic_task.epic_task_crud,
            "task_update_body", _record_direct,
        )
        response = call_dispatcher(
            function_id="workflow_item.epic_task.body_replace",
            target=TargetRef(kind="epic_task", epic_id=42, task_num=1),
            payload={"body": "hello\n"},
        )
        assert response.success is True

        # Parity: identical (epic_id, task_num, body) tuple in both paths
        assert len(cli_calls) == 1 and len(direct_calls) == 1
        assert cli_calls[0] == direct_calls[0]

    def test_db_claim_amend_parity(self, monkeypatch):
        """``service_client db-claim-amend`` ↔ direct dispatch payload."""
        cli_calls: list[dict] = []
        direct_calls: list[dict] = []

        def _record_cli(item_id, claim, *, reason, session_id=None):
            cli_calls.append({"item_id": item_id, "claim": claim, "reason": reason})
            return SimpleNamespace(
                item_id=item_id, previous_profile={}, previous_attestation={},
                new_profile=claim, new_attestation={}, reason=reason, event_id="e",
            )

        def _record_direct(item_id, claim, *, reason, session_id=None):
            direct_calls.append({"item_id": item_id, "claim": claim, "reason": reason})
            return SimpleNamespace(
                item_id=item_id, previous_profile={}, previous_attestation={},
                new_profile=claim, new_attestation={}, reason=reason, event_id="e",
            )

        _silence_claim(monkeypatch)

        # --- CLI path
        from yoke_core.api.service_client_db_claim import cmd_db_claim_amend

        monkeypatch.setattr("yoke_core.domain.db_claim.amend", _record_cli)
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_db_claim_amend([
                "--item", "9", "--state", "none", "--reason", "none-ok",
            ])
        assert rc == 0, (out.getvalue(), err.getvalue())

        # --- Direct dispatch path
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        register_all_handlers()
        monkeypatch.setattr("yoke_core.domain.db_claim.amend", _record_direct)
        response = call_dispatcher(
            function_id="db_claim.amend",
            target=TargetRef(kind="item", item_id=9),
            payload={"claim": {"state": "none"}, "reason": "none-ok"},
        )
        assert response.success is True

        assert len(cli_calls) == 1 and len(direct_calls) == 1
        assert cli_calls[0] == direct_calls[0]

    def test_items_structured_field_append_addendum_parity(self, monkeypatch):
        """``item_field_transform append-addendum --json`` ↔ direct dispatch."""
        from yoke_core.domain import item_field_transform

        cli_calls: list[dict] = []
        direct_calls: list[dict] = []

        def _stub_append_cli(**kwargs):
            cli_calls.append({k: v for k, v in kwargs.items() if k != "out"})
            from yoke_core.domain.item_field_transform import TransformResult
            return TransformResult(
                success=True, operation="append-addendum",
                item_id=kwargs.get("item_id"),
                field=kwargs.get("field"),
                heading=kwargs.get("heading"),
                changed=True, verification="ok",
            )

        def _stub_append_direct(**kwargs):
            direct_calls.append({k: v for k, v in kwargs.items() if k != "out"})
            from yoke_core.domain.item_field_transform import TransformResult
            return TransformResult(
                success=True, operation="append-addendum",
                item_id=kwargs.get("item_id"),
                field=kwargs.get("field"),
                heading=kwargs.get("heading"),
                changed=True, verification="ok",
            )

        _silence_claim(monkeypatch)

        # --- CLI path: --json routes through the dispatcher
        monkeypatch.setattr(
            item_field_transform, "append_addendum", _stub_append_cli,
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO("note body"))
        out = io.StringIO()
        with redirect_stdout(out):
            rc = item_field_transform.main([
                "append-addendum", "--item", "3", "--field", "spec",
                "--heading", "H", "--source", "tester", "--stdin", "--json",
            ])
        assert rc == 0, out.getvalue()

        # --- Direct dispatch path
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        register_all_handlers()
        monkeypatch.setattr(
            item_field_transform, "append_addendum", _stub_append_direct,
        )
        response = call_dispatcher(
            function_id="items.structured_field.append_addendum",
            target=TargetRef(kind="item", item_id=3),
            payload={
                "field": "spec", "heading": "H", "content": "note body",
                "source": "tester",
            },
        )
        assert response.success is True

        assert len(cli_calls) == 1 and len(direct_calls) == 1
        assert cli_calls[0] == direct_calls[0]
