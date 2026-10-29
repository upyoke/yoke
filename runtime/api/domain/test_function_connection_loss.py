"""A dropped control-plane connection answers by name on every in-process path."""

from __future__ import annotations

from unittest.mock import patch

import psycopg
import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
)
from yoke_core.api.function_call_status import status_for_response
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.connected_env_readiness_connector import (
    looks_like_connection_failure,
)
from yoke_core.domain.function_connection_loss import CONNECTION_LOST_CODE
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import register
from runtime.api.domain.test_yoke_function_dispatch import (
    _DispatcherTestBase,
    _Req,
    _Resp,
    _make_request,
    _stable_kwargs,
)

# The wording psycopg raised when the prod driver's connection dropped.
_DROPPED = "consuming input failed: SSL error: unexpected eof while reading"


def _dropping_handler(drops: int):
    calls = []

    def handler(request):
        calls.append(request.function)
        if len(calls) <= drops:
            raise psycopg.OperationalError(_DROPPED)
        return HandlerOutcome(primary_success=True, result_payload={"ok": True})

    return handler, calls


@pytest.mark.parametrize(
    "text",
    [
        _DROPPED,
        "SSL SYSCALL error: EOF detected",
        "server closed the connection unexpectedly",
        "the connection is lost",
    ],
)
def test_mid_statement_drop_reads_as_a_connection_failure(text):
    assert looks_like_connection_failure(psycopg.OperationalError(text))


def test_query_errors_are_not_connection_failures():
    assert not looks_like_connection_failure(
        psycopg.OperationalError('relation "items" does not exist')
    )


class TestDispatchConnectionLoss(_DispatcherTestBase):
    def test_read_retries_once_on_a_fresh_connection(self):
        handler, calls = _dropping_handler(drops=1)
        register("test.read", handler, _Req, _Resp, **_stable_kwargs())

        response = dispatch(_make_request("test.read"))

        assert response.success, response.error
        assert response.result == {"ok": True}
        assert len(calls) == 2

    def test_read_that_drops_twice_is_named(self):
        handler, calls = _dropping_handler(drops=2)
        register("test.read", handler, _Req, _Resp, **_stable_kwargs())

        response = dispatch(_make_request("test.read"))

        assert len(calls) == 2
        assert response.error.code == CONNECTION_LOST_CODE
        assert "nothing was written" in response.error.message
        assert "yoke env list" in response.error.recovery_hint

    def test_database_write_is_never_resent(self):
        self._assert_write_is_never_resent(["db_write"])

    def test_event_write_is_never_resent(self):
        self._assert_write_is_never_resent(["event_emit"])

    def _assert_write_is_never_resent(self, effects):
        handler, calls = _dropping_handler(drops=1)
        register(
            "test.write",
            handler,
            _Req,
            _Resp,
            **_stable_kwargs(side_effects=effects),
        )

        response = dispatch(_make_request("test.write"))

        assert calls == ["test.write"]
        assert response.error.code == CONNECTION_LOST_CODE
        assert "may or may not have committed" in response.error.message
        assert "OperationalError" in response.error.message
        # 500 keeps the HTTPS client from resending a write that may have landed.
        assert status_for_response(response.model_dump()) == 500

    def test_other_handler_exceptions_still_raise_to_their_transport(self):
        def handler(request):
            raise ValueError("bad shape")

        register("test.read", handler, _Req, _Resp, **_stable_kwargs())

        with pytest.raises(ValueError):
            dispatch(_make_request("test.read"))

    def test_driver_surfaces_the_named_refusal_with_the_run_to_resume(self):
        handler, _calls = _dropping_handler(drops=2)
        register(
            "deployment_runs.execution.qa_pending",
            handler,
            _Req,
            _Resp,
            **_stable_kwargs(target_kinds=["workflow_run"]),
        )

        def through_dispatcher(*, function_id, target, payload):
            return dispatch(
                FunctionCallRequest(
                    function=function_id,
                    actor=ActorContext(actor_id="op", session_id="s-1"),
                    target=target,
                    payload=payload,
                )
            )

        with patch.object(control_plane, "call_dispatcher", through_dispatcher):
            with pytest.raises(control_plane.DeploymentControlPlaneError) as raised:
                control_plane.unresolved_qa("run-20261013-010")

        assert raised.value.code == CONNECTION_LOST_CODE
        message = str(raised.value)
        assert "lost its control-plane database connection" in message
        assert "Recovery: Re-read the state" in message
        assert "rerun `yoke watch deploy -- run-20261013-010`" in message


def test_local_transport_types_an_uncaught_engine_exception():
    from yoke_cli.transport import dispatcher

    def raising(request):
        raise KeyError("member")

    response = dispatcher._call_local(_make_request("test.read"), raising)

    assert not response.success
    assert response.error.code == "handler_exception"
    assert "'test.read' raised KeyError" in response.error.message
    assert "yoke feedback --to yoke" in response.error.recovery_hint
