"""Regression checks for service client structured cli sections."""

from __future__ import annotations

from runtime.api.test_service_client_structured_api_adapter_real_cli import (
    SimpleNamespace as SimpleNamespace,
    _silence_claim as _silence_claim,
    io as io,
    redirect_stderr as redirect_stderr,
    redirect_stdout as redirect_stdout,
    sys as sys,
)


class TestRealCliParityMatrix:
    def test_db_claim_amend_parity(self, monkeypatch):
        """``service_client db-claim-amend`` ↔ direct dispatch payload."""
        cli_calls: list[dict] = []
        direct_calls: list[dict] = []

        def _record_cli(item_id, claim, *, reason, session_id=None):
            cli_calls.append({"item_id": item_id, "claim": claim, "reason": reason})
            return SimpleNamespace(
                item_id=item_id,
                previous_profile={},
                previous_attestation={},
                new_profile=claim,
                new_attestation={},
                reason=reason,
                event_id="e",
            )

        def _record_direct(item_id, claim, *, reason, session_id=None):
            direct_calls.append({"item_id": item_id, "claim": claim, "reason": reason})
            return SimpleNamespace(
                item_id=item_id,
                previous_profile={},
                previous_attestation={},
                new_profile=claim,
                new_attestation={},
                reason=reason,
                event_id="e",
            )

        _silence_claim(monkeypatch)

        # --- CLI path
        from yoke_core.api.service_client_db_claim import cmd_db_claim_amend

        monkeypatch.setattr("yoke_core.domain.db_claim.amend", _record_cli)
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_db_claim_amend(
                [
                    "--item",
                    "YOK-9",
                    "--state",
                    "none",
                    "--reason",
                    "none-ok",
                ]
            )
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
            target=TargetRef(kind="item", public_ref="YOK-9"),
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
                success=True,
                operation="append-addendum",
                item_id=kwargs.get("item_id"),
                field=kwargs.get("field"),
                heading=kwargs.get("heading"),
                changed=True,
                verification="ok",
            )

        def _stub_append_direct(**kwargs):
            direct_calls.append({k: v for k, v in kwargs.items() if k != "out"})
            from yoke_core.domain.item_field_transform import TransformResult

            return TransformResult(
                success=True,
                operation="append-addendum",
                item_id=kwargs.get("item_id"),
                field=kwargs.get("field"),
                heading=kwargs.get("heading"),
                changed=True,
                verification="ok",
            )

        _silence_claim(monkeypatch)

        # --- CLI path: --json routes through the dispatcher
        monkeypatch.setattr(
            item_field_transform,
            "append_addendum",
            _stub_append_cli,
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO("note body"))
        out = io.StringIO()
        with redirect_stdout(out):
            rc = item_field_transform.main(
                [
                    "append-addendum",
                    "--item",
                    "YOK-3",
                    "--field",
                    "spec",
                    "--heading",
                    "H",
                    "--source",
                    "tester",
                    "--stdin",
                    "--json",
                ]
            )
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
            item_field_transform,
            "append_addendum",
            _stub_append_direct,
        )
        response = call_dispatcher(
            function_id="items.structured_field.append_addendum",
            target=TargetRef(kind="item", public_ref="YOK-3"),
            payload={
                "field": "spec",
                "heading": "H",
                "content": "note body",
                "source": "tester",
            },
        )
        assert response.success is True

        assert len(cli_calls) == 1 and len(direct_calls) == 1
        assert cli_calls[0] == direct_calls[0]
