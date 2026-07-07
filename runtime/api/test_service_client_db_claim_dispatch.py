"""AC-8.4 dispatcher-parity tests for ``service_client db-claim-amend``.

Verifies that the CLI builds a :class:`FunctionCallRequest` for
``db_claim.amend`` and calls
:func:`yoke_core.domain.yoke_function_dispatch.dispatch` rather than
reaching directly into :func:`yoke_core.domain.db_claim.amend`.

Each test patches the handler's ``amend`` import to record what the
dispatcher hands the domain owner, and silences ``verify_claim`` because
the fake DB has no harness_sessions rows.
"""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace


class TestDbClaimAmendDispatch:
    """AC-8.4 — ``db-claim-amend`` routes through ``db_claim.amend`` dispatcher."""

    def _patch_amend(self, monkeypatch, result=None, raise_exc=None):
        """Patch the handler's import of ``amend`` to a recording stub.

        Returns the captured ``calls`` list. Each entry is the keyword
        argv dict (item_id, claim, reason, session_id) the handler hands
        the domain owner.
        """
        calls: list[dict] = []
        from yoke_core.domain.handlers import db_claim as db_claim_handler

        def _record(item_id, claim, *, reason, session_id=None):
            calls.append({
                "item_id": item_id,
                "claim": claim,
                "reason": reason,
                "session_id": session_id,
            })
            if raise_exc is not None:
                raise raise_exc
            return result if result is not None else SimpleNamespace(
                item_id=item_id,
                previous_profile={},
                previous_attestation={},
                new_profile=claim,
                new_attestation={},
                reason=reason,
                event_id="evt-1",
            )

        # Patch through the handler module's local binding so the
        # dispatcher hop is visible. The handler imports ``amend``
        # lazily inside ``handle_amend``, so the patch must target the
        # module the lazy import resolves to.
        monkeypatch.setattr(
            "yoke_core.domain.db_claim.amend", _record,
        )
        # Silence claim verification — no harness_sessions rows in tests.
        from yoke_core.domain import yoke_function_dispatch as dispatch_module
        monkeypatch.setattr(
            dispatch_module, "verify_claim", lambda *a, **kw: None,
        )
        return calls

    def test_state_none_routes_through_dispatcher(self, monkeypatch):
        from yoke_core.api.service_client_db_claim import cmd_db_claim_amend

        calls = self._patch_amend(monkeypatch)

        out = StringIO()
        err = StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_db_claim_amend([
                "--item", "YOK-42", "--state", "none",
                "--reason", "no governed DB work",
            ])
        assert rc == 0, (out.getvalue(), err.getvalue())
        assert len(calls) == 1
        assert calls[0]["item_id"] == 42
        assert calls[0]["claim"] == {"state": "none"}
        assert calls[0]["reason"] == "no governed DB work"
        data = json.loads(out.getvalue())
        assert data["success"] is True
        assert data["item_id"] == 42
        assert data["reason"] == "no governed DB work"

    def test_json_mode_emits_function_call_response_envelope(self, monkeypatch):
        from yoke_core.api.service_client_db_claim import cmd_db_claim_amend

        self._patch_amend(monkeypatch)

        out = StringIO()
        with redirect_stdout(out):
            rc = cmd_db_claim_amend([
                "--item", "YOK-7", "--state", "none",
                "--reason", "noop", "--json",
            ])
        assert rc == 0, out.getvalue()
        envelope = json.loads(out.getvalue())
        assert envelope["success"] is True
        assert envelope["function"] == "db_claim.amend"
        result = envelope["result"]
        assert result["item_id"] == 7
        assert "previous_profile" in result
        assert "new_profile" in result

    def test_payload_inline_json_routes_through_dispatcher(self, monkeypatch):
        from yoke_core.api.service_client_db_claim import cmd_db_claim_amend

        calls = self._patch_amend(monkeypatch)
        claim_json = json.dumps({"state": "declared", "intent": "apply"})

        out = StringIO()
        with redirect_stdout(out):
            rc = cmd_db_claim_amend([
                "--item", "5", "--payload", claim_json,
                "--reason", "declared",
            ])
        assert rc == 0, out.getvalue()
        assert calls[0]["claim"] == {"state": "declared", "intent": "apply"}

    def test_validation_failure_emits_error_to_stderr(self, monkeypatch):
        from yoke_core.domain.db_claim import DbClaimAmendmentError
        from yoke_core.api.service_client_db_claim import cmd_db_claim_amend

        self._patch_amend(
            monkeypatch,
            raise_exc=DbClaimAmendmentError("invalid state transition"),
        )

        out = StringIO()
        err = StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_db_claim_amend([
                "--item", "1", "--state", "none",
                "--reason", "x",
            ])
        assert rc == 1
        err_body = json.loads(err.getvalue())
        assert err_body["success"] is False
        assert "invalid state transition" in err_body["message"]
