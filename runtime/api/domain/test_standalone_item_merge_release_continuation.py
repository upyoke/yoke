"""Merge close-out asks for a prepared release through the dispatcher.

Ordinary HTTPS projects have no local Postgres. Continuation therefore
dispatches ``deployment_runs.continue_for_item`` with the merge session on
the actor and maps the real ``FunctionCallResponse`` / ``ContinueResult``
shape. It must not open a database, invent an unresolved ref, or name a
db-admin retry.
"""

from __future__ import annotations

from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_core.domain import standalone_item_merge_release_continuation as release_flow
from yoke_core.engines.runs_continue_for_item import (
    ContinueResult,
    OUTCOME_BOUND,
    OUTCOME_NONE,
    OUTCOME_WAITING,
)

PUBLIC_REF = "ITEM-7"
ITEM_ID = 7
LINEAGE = "a" * 40
SESSION = "merge-session"


def _ok(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=release_flow.CONTINUE_FUNCTION, version="v1",
        result=result,
    )


def _err(code: str, message: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=release_flow.CONTINUE_FUNCTION,
        version="v1",
        error=FunctionError(code=code, message=message),
    )


def _forbid_local_db(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("continuation must not open a control-plane database")

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", boom)
    monkeypatch.setattr(
        "yoke_core.engines.runs_continue_for_item.continue_for_item", boom,
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_identity_item_ref.item_ref_for_id", boom,
    )


def _patch_dispatch(monkeypatch, handler):
    captured: list[dict] = []

    def fake_dispatch(**kwargs):
        captured.append(kwargs)
        return handler(kwargs)

    monkeypatch.setattr(release_flow, "call_dispatcher", fake_dispatch)
    return captured


class TestDispatcherResultShape:
    def test_none_from_continue_result_is_quiet(self, monkeypatch):
        _forbid_local_db(monkeypatch)
        payload = ContinueResult(ok=True, outcome=OUTCOME_NONE).to_dict()
        calls = _patch_dispatch(monkeypatch, lambda _k: _ok(payload))

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, session_id=SESSION, public_ref=PUBLIC_REF,
        )

        assert fragment is None
        assert warning == ""
        assert payload["ok"] is True
        assert payload["outcome"] == OUTCOME_NONE
        assert payload["waiting_on"] == []
        request = calls[0]
        assert request["function_id"] == release_flow.CONTINUE_FUNCTION
        assert request["target"] == TargetRef(
            kind="item", item_id=ITEM_ID, public_ref=PUBLIC_REF,
        )
        assert request["actor"].session_id == SESSION

    def test_waiting_maps_continue_result(self, monkeypatch):
        _forbid_local_db(monkeypatch)
        payload = ContinueResult(
            ok=True, outcome=OUTCOME_WAITING, run_id="run-1",
            waiting_on=["ITEM-8"],
        ).to_dict()
        _patch_dispatch(monkeypatch, lambda _k: _ok(payload))

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, session_id=SESSION, public_ref=PUBLIC_REF,
        )

        assert warning == ""
        assert fragment == {
            "run_id": "run-1",
            "outcome": OUTCOME_WAITING,
            "waiting_on": ["ITEM-8"],
        }

    def test_bound_maps_continue_result(self, monkeypatch):
        _forbid_local_db(monkeypatch)
        payload = ContinueResult(
            ok=True, outcome=OUTCOME_BOUND, run_id="run-1",
            release_lineage=LINEAGE, handed_off_to="session-holder",
            message_id="msg-1",
        ).to_dict()
        _patch_dispatch(monkeypatch, lambda _k: _ok(payload))

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, session_id=SESSION, public_ref=PUBLIC_REF,
        )

        assert warning == ""
        assert fragment == {
            "run_id": "run-1",
            "outcome": OUTCOME_BOUND,
            "release_lineage": LINEAGE,
            "handed_off_to": "session-holder",
            "message_id": "msg-1",
        }

    def test_dispatcher_error_stays_explicit(self, monkeypatch):
        _forbid_local_db(monkeypatch)
        _patch_dispatch(
            monkeypatch,
            lambda _k: _err("duplicate_prepared_run", "duplicate_prepared_run"),
        )

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, session_id=SESSION, public_ref=PUBLIC_REF,
        )

        assert fragment is None
        assert "duplicate_prepared_run" in warning
        assert PUBLIC_REF in warning
        assert "not a merge failure" in warning
        assert "unresolved" not in warning
        assert "db-admin" not in warning
        assert "re-run this command" not in warning.lower()

    def test_missing_hand_off_maps_continue_result(self, monkeypatch):
        _forbid_local_db(monkeypatch)
        payload = ContinueResult(
            ok=True, outcome=OUTCOME_BOUND, run_id="run-1",
            release_lineage=LINEAGE, handed_off_to="session-holder",
        ).to_dict()
        _patch_dispatch(monkeypatch, lambda _k: _ok(payload))

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, session_id=SESSION, public_ref=PUBLIC_REF,
        )

        assert fragment["run_id"] == "run-1"
        assert "message_id" not in payload
        assert PUBLIC_REF in warning
        assert "continue-for-item" in warning
        assert "not delivered" in warning
        assert "re-run this command" not in warning.lower()
        assert "db-admin" not in warning


class TestHttpsAndLocalAuthority:
    def _https(self, monkeypatch, result):
        import yoke_cli.transport.dispatcher as dispatcher_mod
        from yoke_cli.transport import https as https_mod

        conn = HttpsConnection(
            api_url="https://api.example", token="tok", env="prod",
        )
        monkeypatch.setattr(https_mod, "resolve_https_connection", lambda: conn)
        captured: dict = {}

        def fake_relay(request, connection, **_k):
            captured["request"] = request
            captured["connection"] = connection
            return _ok(result)

        monkeypatch.setattr(https_mod, "relay_https", fake_relay)
        monkeypatch.setattr(
            dispatcher_mod, "_call_local",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("https continuation must not dispatch locally")
            ),
        )
        return captured

    def _local(self, monkeypatch, result):
        import yoke_cli.transport.dispatcher as dispatcher_mod
        from yoke_cli.transport import https as https_mod

        monkeypatch.setattr(https_mod, "resolve_https_connection", lambda: None)
        captured: dict = {}

        def fake_local(request, *_a, **_k):
            captured["request"] = request
            return _ok(result)

        monkeypatch.setattr(dispatcher_mod, "_call_local", fake_local)
        monkeypatch.setattr(
            https_mod, "relay_https",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("local continuation must not relay https")
            ),
        )
        return captured

    def test_https_binds_the_merge_session(self, monkeypatch):
        _forbid_local_db(monkeypatch)
        payload = ContinueResult(ok=True, outcome=OUTCOME_NONE).to_dict()
        captured = self._https(monkeypatch, payload)

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, session_id=SESSION, public_ref=PUBLIC_REF,
        )

        assert fragment is None and warning == ""
        assert captured["request"].function == release_flow.CONTINUE_FUNCTION
        assert captured["request"].actor.session_id == SESSION
        assert captured["request"].target.item_id == ITEM_ID
        assert captured["connection"].env == "prod"

    def test_local_authority_binds_the_merge_session(self, monkeypatch):
        _forbid_local_db(monkeypatch)
        payload = ContinueResult(
            ok=True, outcome=OUTCOME_BOUND, run_id="run-1",
            release_lineage=LINEAGE, handed_off_to="holder",
            message_id="msg-1",
        ).to_dict()
        captured = self._local(monkeypatch, payload)

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, session_id=SESSION, public_ref=PUBLIC_REF,
        )

        assert warning == ""
        assert fragment["run_id"] == "run-1"
        assert captured["request"].actor.session_id == SESSION
        assert captured["request"].function == release_flow.CONTINUE_FUNCTION
