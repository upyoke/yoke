"""Machine admission commands, plain-terminal identity and older-server recovery."""

from contextlib import nullcontext
import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_machine_authorization_codes import (
    conn as _conn_fixture,
    pending as start,
)
from yoke_cli.commands import _helpers, connect, registry
from yoke_cli.commands.adapters import machine_admission as commands
from yoke_cli.commands.adapters.admission_floor_recovery import ADMISSION_FLOOR_RECOVERY
from yoke_cli.config import local_reachability, hosted_machine_authorization as hosted
from yoke_cli.transport import dispatcher, function_version_skew, https
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_core.domain.handlers import _register_inbox, machine_authorization as handlers
from yoke_core.domain.terminal_reachable_functions import TERMINAL_RECIPES

conn = _conn_fixture
VIEWER = {"actor_id": 1, "name": "Pat"}
DETAIL = {"code": "K7F2", "machine": "Pat's laptop", "viewer": VIEWER}


@pytest.fixture()
def transport(monkeypatch):
    state = SimpleNamespace(calls=[], missing=None, mode="self-host", handler=None)
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(commands, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(dispatcher, "_resolve_session_id", lambda: "")
    monkeypatch.delenv("YOKE_ACTOR_ID", raising=False)
    monkeypatch.setattr(
        https,
        "resolve_https_connection",
        lambda: https.HttpsConnection("https://team.example", "test-token", env="team"),
    )
    monkeypatch.setattr(
        function_version_skew, "local_handshake_version", lambda: "2.0.0"
    )
    monkeypatch.setattr(
        dispatcher, "warn_if_behind_active_connection", lambda **kw: None
    )

    def relay(request, connection, *, handshake, **kwargs):
        handshake.engine_version = "1.0.0"
        state.calls.append(request)
        if state.missing == request.function:
            return FunctionCallResponse(
                success=False,
                function=request.function,
                request_id=request.request_id,
                error=FunctionError(
                    code="function_not_registered",
                    message="function id is not registered",
                ),
            )
        if state.handler:
            outcome = state.handler(request)
            return FunctionCallResponse(
                success=outcome.primary_success,
                function=request.function,
                request_id=request.request_id,
                result=outcome.result_payload,
                error=outcome.error,
            )
        if request.function.endswith(".pending"):
            result = {
                "viewer": VIEWER,
                "mode": state.mode,
                "requests": [
                    {
                        **DETAIL,
                        "requested_by": None,
                        "expires_at": "2030-01-01T00:00:00Z",
                    }
                ],
            }
        elif request.function.endswith(".get"):
            result = {"authorization": DETAIL}
        else:
            result = {"authorization": {"decision": request.payload["action"]}}
        return FunctionCallResponse(
            success=True,
            function=request.function,
            request_id=request.request_id,
            result=result,
        )

    monkeypatch.setattr(https, "relay_https", relay)
    return state


def test_pending_lists_match_details_and_json_preserves_result(transport, capsys):
    assert commands.machines_pending([]) == 0
    human = capsys.readouterr().out
    assert all(
        value in human
        for value in (
            "K7F2",
            "Pat's laptop",
            "Unbound",
            "2030-01-01T00:00:00Z",
            "Pat (actor 1)",
        )
    )
    assert commands.machines_pending(["--json"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["viewer"] == VIEWER
    assert result["requests"][0]["code"] == "K7F2"
    assert all(
        call.payload == {} and call.target.kind == "global" for call in transport.calls
    )


def test_local_pending_prints_reachability_but_json_keeps_function_result(
    transport, capsys
):
    transport.mode = "local"
    assert commands.machines_pending([]) == 0
    assert (
        capsys.readouterr().out.strip() == local_reachability.LOCAL_REACHABILITY_NOTICE
    )
    assert commands.machines_pending(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["mode"] == "local"


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_plain_terminal_calls_real_registered_decision_as_token_actor(
    conn, monkeypatch, transport, capsys, action
):
    conn.execute("UPDATE actors SET name='Pat' WHERE id=1")
    code = start(conn)["user_code"]
    rows = {}
    _register_inbox.register(
        SimpleNamespace(
            register=lambda fid, fn, *args, **kw: rows.update({fid: (fn, kw)})
        )
    )
    monkeypatch.setattr(handlers.db_helpers, "connect", lambda: nullcontext(conn))

    def bound_call(request):
        assert request.actor.session_id == "" and request.actor.actor_id is None
        assert request.target.kind == "global"
        bound = request.model_copy(
            update={"actor": ActorContext(actor_id="1", session_id="")}
        )
        return rows[request.function][0](bound)

    transport.handler = bound_call
    _, adapter, _ = registry.resolve(["machines", action, code.lower()])
    assert adapter([code.lower()]) == 0
    output = capsys.readouterr().out
    assert "Pat (actor 1)" in output and "Pat's laptop" in output
    assert output.index("Deciding as") < output.index(
        "Approved" if action == "approve" else "Denied"
    )
    assert [call.function for call in transport.calls] == [
        "machine_authorization.get",
        "machine_authorization.resolve",
    ]
    assert transport.calls[-1].payload == {"code": code, "action": action}
    assert tuple(
        conn.execute(
            "SELECT actor_id,decision FROM machine_authorization_codes"
        ).fetchone()
    ) == (1, action)
    assert rows["machine_authorization.pending"][1]["adapter_status"] == "live"
    assert rows["machine_authorization.resolve"][1]["ambient_session_required"] is False
    assert "machine_authorization.resolve" in TERMINAL_RECIPES


@pytest.mark.parametrize("missing", ["pending", "get", "resolve"])
def test_missing_server_function_names_floor_and_exact_recovery(
    transport, capsys, missing
):
    transport.missing = f"machine_authorization.{missing}"
    adapter, args = (
        (commands.machines_pending, [])
        if missing == "pending"
        else (commands.machines_approve, ["k7f2"])
    )
    assert adapter([*args, "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "function_version_skew"
    assert "(minimum serving version next-release)" in error["message"]
    assert error["recovery_hint"].endswith(ADMISSION_FLOOR_RECOVERY)
    assert "wait for" not in error["recovery_hint"].lower()
    assert "retry after deploy" not in error["recovery_hint"].lower()
    if missing == "get":
        assert len(transport.calls) == 1


def test_helper_without_hint_preserves_existing_recovery_bytes(transport, capsys):
    function_id = "machine_authorization.pending"
    transport.missing = function_id
    original = dispatcher.call_dispatcher(
        function_id=function_id, target=TargetRef(kind="global")
    )
    assert (
        _helpers.dispatch_and_emit(
            function_id=function_id,
            target=TargetRef(kind="global"),
            payload={},
            session_id=None,
            json_mode=True,
        )
        == 1
    )
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["recovery_hint"].encode() == original.error.recovery_hint.encode()
    assert ADMISSION_FLOOR_RECOVERY not in error["recovery_hint"]


@pytest.mark.parametrize(
    "adapter,args",
    [
        (commands.machines_approve, []),
        (commands.machines_deny, []),
        (commands.machines_pending, ["extra"]),
    ],
)
def test_bad_usage_never_dispatches(transport, adapter, args):
    assert adapter(args) == 2
    assert transport.calls == []


@pytest.mark.parametrize("value,expected", [("local-postgres", True), ("https", False)])
def test_local_connection_fact_uses_active_transport(monkeypatch, value, expected):
    monkeypatch.setattr(
        local_reachability.machine_config,
        "active_connection",
        lambda path: {"transport": value},
    )
    assert local_reachability.active_connection_is_local() is expected


def test_connect_notification_teaches_matching_code_and_approval(monkeypatch, capsys):
    def authorize(url, **kwargs):
        kwargs["notify"](
            hosted.PendingMachineAuthorization(
                platform_url=url,
                device_code="secret",
                user_code="K7F2",
                verification_uri=url + "/connect",
                verification_uri_complete=url + "/connect?user_code=K7F2",
                expires_in=600,
                interval=2,
            ),
            hosted.BrowserOpenResult(opened=True, method="webbrowser"),
        )
        raise hosted.HostedMachineAuthorizationError(
            "authorization_expired", "start again"
        )

    monkeypatch.setattr(hosted, "authorize", authorize)
    assert (
        connect._connect_hosted(
            SimpleNamespace(
                url="https://team.example",
                json_mode=False,
                self_host=True,
                config=None,
                name=None,
                no_activate=False,
            )
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "Match code: K7F2" in output
    assert "`yoke machines approve K7F2`" in output
    assert "Machines → Waiting for approval" in output
