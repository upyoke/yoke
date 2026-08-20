"""Typed version-skew gate over the relayed function-call transport."""

from __future__ import annotations

from yoke_cli.transport import dispatcher as yoke_dispatcher
from yoke_cli.transport import function_version_skew
from yoke_cli.transport import https as yoke_transport
from yoke_cli.transport.function_version_skew import (
    SKEW_ERROR_CODE,
    UNKNOWN_VERSION,
    skew_error,
)
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

# Any function id the CLI build resolves works here; this one is a plain
# read whose adapter has shipped for long enough to be a stable fixture.
SERVED_LOCALLY = "items.get.run"


def _request(function_id: str = SERVED_LOCALLY) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="s1"),
        target=TargetRef(kind="global"),
        request_id="req-1",
    )


def _not_registered(request, _connection, **_kwargs) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code="function_not_registered",
            message="function id is not registered",
        ),
    )


def _relay_returning(response_factory, server_version: str):
    def relay(request, connection, *, handshake=None, **_kwargs):
        if handshake is not None:
            handshake.engine_version = server_version
        return response_factory(request, connection)

    return relay


def _dispatch_over_https(
    monkeypatch,
    *,
    server_version: str,
    client_version: str,
    function_id: str = SERVED_LOCALLY,
    env: str = "prod",
    relay=None,
) -> FunctionCallResponse:
    monkeypatch.setattr(
        yoke_transport,
        "resolve_https_connection",
        lambda path=None: HttpsConnection("https://api.example", "tok", env=env),
    )
    monkeypatch.setattr(
        yoke_transport,
        "relay_https",
        relay or _relay_returning(_not_registered, server_version),
    )
    monkeypatch.setattr(
        yoke_dispatcher, "local_handshake_version", lambda: client_version
    )
    return yoke_dispatcher.call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="a", session_id="s1"),
    )


class TestSkewErrorDirection:
    def test_client_ahead_points_at_the_deploy(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="2.0.0",
            server_version="1.9.0",
        )
        assert error.code == SKEW_ERROR_CODE
        assert "deployed server predates this client build" in error.recovery_hint

    def test_client_behind_points_at_the_installer(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="1.9.0",
            server_version="2.0.0",
        )
        assert "rerun the public installer" in error.recovery_hint.lower()

    def test_unresolvable_versions_name_both_recoveries(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="",
            server_version="2.0.0",
        )
        hint = error.recovery_hint.lower()
        assert "retry after deploy" in hint
        assert "rerun the public installer" in hint
        assert UNKNOWN_VERSION in error.message

    def test_development_suffixes_still_order(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="2.1.0.dev4+g89ab",
            server_version="2.0.0",
        )
        assert "deployed server predates this client build" in error.recovery_hint

    def test_same_release_development_and_launch_builds_are_not_ordered(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="0.1.1.dev5+gabc",
            server_version="0.1.1+launch.246",
        )
        assert "do not establish which side is behind" in error.recovery_hint

    def test_malformed_version_does_not_compare_equal(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="0.1.1junk",
            server_version="0.1.1",
        )
        assert "do not establish which side is behind" in error.recovery_hint

    def test_launch_number_orders_releases_on_same_public_version(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="0.1.1+launch.246",
            server_version="0.1.1+launch.245",
        )
        assert "deployed server predates this client build" in error.recovery_hint

    def test_equal_versions_do_not_claim_a_direction(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="2.0.0",
            server_version="2.0.0",
        )
        assert "do not establish which side is behind" in error.recovery_hint

    def test_env_name_is_named_when_known(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="2.0.0",
            server_version="1.0.0",
            env_name="prod",
        )
        assert "env 'prod' does not serve" in error.message

    def test_extra_hint_is_appended_below_the_recovery(self):
        error = skew_error(
            function_id=SERVED_LOCALLY,
            client_version="2.0.0",
            server_version="1.0.0",
            extra_hint="rerun with `yoke --env local items get YOK-1`.",
        )
        assert error.recovery_hint.index("deployed server predates") < (
            error.recovery_hint.index("yoke --env local")
        )


class TestRelayedSkewGate:
    def test_newer_client_gets_the_typed_error(self, monkeypatch):
        response = _dispatch_over_https(
            monkeypatch, server_version="1.0.0", client_version="2.0.0"
        )
        assert response.success is False
        assert response.error.code == SKEW_ERROR_CODE
        assert SERVED_LOCALLY in response.error.message
        assert "client engine version 2.0.0" in response.error.message
        assert "server engine version 1.0.0" in response.error.message
        assert "env 'prod'" in response.error.message
        assert "deployed server predates this client build" in (
            response.error.recovery_hint
        )

    def test_newer_server_gets_the_client_update_recovery(self, monkeypatch):
        response = _dispatch_over_https(
            monkeypatch, server_version="2.0.0", client_version="1.0.0"
        )
        assert response.error.code == SKEW_ERROR_CODE
        assert "rerun the public installer" in response.error.recovery_hint.lower()

    def test_unknown_function_keeps_the_servers_own_answer(self, monkeypatch):
        response = _dispatch_over_https(
            monkeypatch,
            server_version="2.0.0",
            client_version="1.0.0",
            function_id="missing.family.op",
        )
        assert response.error.code == "function_not_registered"

    def test_other_server_errors_are_untouched(self, monkeypatch):
        def denied(request, _connection) -> FunctionCallResponse:
            return FunctionCallResponse(
                success=False,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                error=FunctionError(code="permission_denied", message="nope"),
            )

        response = _dispatch_over_https(
            monkeypatch,
            server_version="1.0.0",
            client_version="2.0.0",
            relay=_relay_returning(denied, "1.0.0"),
        )
        assert response.error.code == "permission_denied"

    def test_successful_relay_is_untouched(self, monkeypatch):
        def ok(request, _connection) -> FunctionCallResponse:
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={"item_id": 1},
            )

        response = _dispatch_over_https(
            monkeypatch,
            server_version="1.0.0",
            client_version="2.0.0",
            relay=_relay_returning(ok, "1.0.0"),
        )
        assert response.success is True
        assert response.error is None

    def test_silent_server_still_yields_the_typed_error(self, monkeypatch):
        response = _dispatch_over_https(
            monkeypatch, server_version="", client_version=""
        )
        assert response.error.code == SKEW_ERROR_CODE
        assert f"server engine version {UNKNOWN_VERSION}" in response.error.message


class TestLocalDispatchIsImmune:
    def test_in_process_not_registered_is_left_alone(self, monkeypatch):
        """One process holds one registry, so there is no skew to name."""
        monkeypatch.setattr(
            yoke_transport, "resolve_https_connection", lambda path=None: None
        )
        response = yoke_dispatcher.call_dispatcher(
            function_id=SERVED_LOCALLY,
            target=TargetRef(kind="global"),
            actor=ActorContext(actor_id="a", session_id="s1"),
            _local_dispatch=lambda request: _not_registered(request, None),
        )
        assert response.error.code == "function_not_registered"


class TestLocalFunctionIds:
    def test_registry_ids_are_resolvable(self):
        assert SERVED_LOCALLY in function_version_skew.local_function_ids()
        assert "missing.family.op" not in function_version_skew.local_function_ids()
