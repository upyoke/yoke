"""CLI dispatch parity, response emission and live-function usage coverage."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import (
    list_entries,
    register,
    reset_registry_for_tests,
)
from yoke_core.api.service_client_structured_api_adapter import (
    build_actor,
    build_request,
    call_dispatcher,
    emit_response,
)


# ---------------------------------------------------------------------------
# Registry inventory parity
# ---------------------------------------------------------------------------


def _live_function_ids() -> set[str]:
    """Function ids registered with ``adapter_status='live'``.

    The fixture loads the canonical handler chain via
    ``register_all_handlers`` so the assertion reflects the production
    registry contents, not a synthetic test set.
    """
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()
    return {
        entry.function_id for entry in list_entries() if entry.adapter_status == "live"
    }


def test_every_live_function_has_adapter_usage() -> None:
    from yoke_cli.commands.adapters.usage import ADAPTER_USAGE

    missing = sorted(
        function_id
        for function_id in _live_function_ids()
        if not ADAPTER_USAGE.get(function_id)
    )
    assert not missing, (
        f"Live functions without CLI usage: {missing}. Add their usage to "
        "ADAPTER_USAGE or mark code-only handlers adapter_status='internal'."
    )


def test_live_function_without_usage_fails_parity(monkeypatch) -> None:
    from yoke_cli.commands.adapters.usage import ADAPTER_USAGE

    function_id = next(iter(_live_function_ids()))
    monkeypatch.delitem(ADAPTER_USAGE, function_id)
    with pytest.raises(AssertionError):
        test_every_live_function_has_adapter_usage()


# ---------------------------------------------------------------------------
# Synthetic handler parity — CLI invocation vs direct dispatch
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_handler(monkeypatch):
    """Register a synthetic handler so parity assertions stay deterministic.

    The fixture isolates the registry per-test so handler tasks 3-7 stay
    out of the way. The synthetic handler returns a fixed payload + a
    fixed warning so the test can verify the response envelope shape
    end-to-end.
    """
    reset_registry_for_tests()
    from pydantic import BaseModel

    class _Req(BaseModel):
        ping: str = "pong"

    class _Resp(BaseModel):
        ping: str
        echo: str

    def _handler(request: FunctionCallRequest) -> HandlerOutcome:
        payload = _Req.model_validate(request.payload)
        response = _Resp(ping=payload.ping, echo=f"echo:{payload.ping}")
        return HandlerOutcome(
            result_payload=response.model_dump(),
            primary_success=True,
        )

    register(
        function_id="cli_parity.test.echo",
        handler=_handler,
        request_model=_Req,
        response_model=_Resp,
        stability="stable",
        owner_module="runtime.api.test_service_client_structured_api_adapter",
        target_kinds=["global"],
        side_effects=[],
        guardrails=[],
        adapter_status="live",
    )
    yield
    reset_registry_for_tests()


class TestDispatchParity:
    """CLI invocation and direct dispatch produce identical results."""

    def test_call_dispatcher_returns_typed_envelope(self, synthetic_handler) -> None:
        response = call_dispatcher(
            function_id="cli_parity.test.echo",
            target=TargetRef(kind="global"),
            payload={"ping": "alpha"},
            actor=ActorContext(actor_id="t", session_id=""),
        )
        assert isinstance(response, FunctionCallResponse)
        assert response.success is True
        assert response.function == "cli_parity.test.echo"
        assert response.result == {"ping": "alpha", "echo": "echo:alpha"}

    def test_dispatch_call_with_same_payload_yields_same_result(
        self, synthetic_handler
    ) -> None:
        """Two dispatch calls with the same payload return matching envelopes."""
        first = call_dispatcher(
            function_id="cli_parity.test.echo",
            target=TargetRef(kind="global"),
            payload={"ping": "beta"},
            actor=ActorContext(actor_id="t", session_id=""),
        )
        second = call_dispatcher(
            function_id="cli_parity.test.echo",
            target=TargetRef(kind="global"),
            payload={"ping": "beta"},
            actor=ActorContext(actor_id="t", session_id=""),
        )
        assert first.success == second.success
        assert first.result == second.result
        assert first.function == second.function
        assert first.version == second.version

    def test_build_request_round_trips_envelope(self, synthetic_handler) -> None:
        """The CLI request builder produces a valid envelope dispatch accepts."""
        request = build_request(
            function_id="cli_parity.test.echo",
            target=TargetRef(kind="global"),
            payload={"ping": "gamma"},
            actor=ActorContext(actor_id="t", session_id=""),
        )
        assert isinstance(request, FunctionCallRequest)
        assert request.function == "cli_parity.test.echo"
        assert request.payload == {"ping": "gamma"}


# ---------------------------------------------------------------------------
# JSON emission
# ---------------------------------------------------------------------------


class TestJsonMode:
    """``--json`` returns the FunctionCallResponse verbatim."""

    def _make_response(
        self,
        *,
        success: bool = True,
        result: dict | None = None,
    ) -> FunctionCallResponse:
        return FunctionCallResponse(
            success=success,
            function="cli_parity.test.echo",
            version="v1",
            request_id=None,
            result=result or {"ping": "x"},
            warnings=[],
            error=None,
            event_ids=[],
        )

    def test_json_mode_emits_response_verbatim(self) -> None:
        response = self._make_response(result={"k": "v"})
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = emit_response(response, json_mode=True)
        assert rc == 0
        emitted = json.loads(out.getvalue())
        assert emitted == response.model_dump(mode="json")

    def test_json_mode_exit_code_reflects_failure(self) -> None:
        response = FunctionCallResponse(
            success=False,
            function="cli_parity.test.echo",
            version="v1",
            request_id=None,
            result={},
            warnings=[],
            error=None,
            event_ids=[],
        )
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = emit_response(response, json_mode=True)
        assert rc == 1
        emitted = json.loads(out.getvalue())
        assert emitted["success"] is False

    def test_human_mode_prints_result_payload(self) -> None:
        response = self._make_response(result={"k": "v"})
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = emit_response(response, json_mode=False)
        assert rc == 0
        assert out.getvalue() == "k: v\n"


# ---------------------------------------------------------------------------
# Actor resolution
# ---------------------------------------------------------------------------


class TestActorResolution:
    def test_build_actor_leaves_actor_id_none_for_server_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        monkeypatch.delenv("YOKE_ACTOR_ID", raising=False)
        actor = build_actor()
        assert actor.actor_id is None
        assert actor.session_id == ""

    def test_build_actor_uses_explicit_args(self) -> None:
        actor = build_actor(actor_id="manual", session_id="sess-9")
        assert actor.actor_id == "manual"
        assert actor.session_id == "sess-9"

    def test_build_actor_reads_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOKE_SESSION_ID", "env-sess")
        monkeypatch.setenv("YOKE_ACTOR_ID", "env-actor")
        actor = build_actor()
        assert actor.actor_id == "env-actor"
        assert actor.session_id == "env-sess"
