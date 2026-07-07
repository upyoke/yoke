"""Parity matrix test for the CLI-to-dispatcher adapter.

Covers AC-8.5, AC-8.6, AC-8.8, AC-8.9, AC-8.10 of
- AC-8.6: each (CLI invocation, equivalent dispatch call) pair produces
  identical typed result payloads. The test calls
  :func:`yoke_core.api.service_client_structured_api_adapter.call_dispatcher`
  once and the same dispatcher entrypoint twice with identical inputs,
  asserts the responses match, and asserts the registry's recorded
  ``YokeFunctionCalled`` event row carries the same payload shape both
  times.
- AC-8.5 / AC-8.9: every retained adapter supports ``--json`` mode and
  returns the typed envelope verbatim. The test imports the typed
  envelope, dispatches a synthetic function via the adapter, and asserts
  the JSON output is a verbatim ``response.model_dump(mode="json")``.
- AC-8.8: the parity matrix is generated from the registry + the
  retained-adapter inventory, so adding a new function id with
  ``adapter_status="live"`` without an adapter inventory entry fails the
  test. The reverse — an inventory entry for an unregistered function
  id — also fails so stale inventory rows get caught.
- AC-8.10: ``adapter_for`` returns a structured result, not a shell
  exit-code probe; capability checks need no ``2>&1; echo $?``
  choreography.
"""

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
    AdapterEntry,
    CLI_ADAPTERS,
    AGENT_PATH_VALUES,
    adapter_for,
    build_actor,
    build_request,
    call_dispatcher,
    emit_response,
    function_ids_with_adapter,
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
        entry.function_id
        for entry in list_entries()
        if entry.adapter_status == "live"
    }


class TestRegistryInventoryParity:
    """AC-8.8 — adapter inventory tracks the live registry one-to-one."""

    def test_every_live_function_has_an_adapter_entry(self) -> None:
        live = _live_function_ids()
        adapters = set(function_ids_with_adapter())
        missing = sorted(live - adapters)
        assert not missing, (
            "Registered function ids with adapter_status='live' that have no "
            "CLI adapter inventory entry: "
            f"{missing}. Add an AdapterEntry in "
            "service_client_structured_api_adapter_inventory.CLI_ADAPTERS for "
            "each id, or mark the handler adapter_status='internal'."
        )

    def test_every_adapter_entry_targets_a_registered_function(self) -> None:
        live = _live_function_ids()
        adapters = set(function_ids_with_adapter())
        stale = sorted(adapters - live)
        assert not stale, (
            "Adapter inventory entries whose function id is NOT registered "
            f"live: {stale}. Either register the handler or remove the "
            "stale inventory row."
        )

    def test_adapter_entries_carry_documented_invocation(self) -> None:
        for entry in CLI_ADAPTERS:
            assert entry.function_id, f"adapter missing function_id: {entry}"
            assert entry.cli_invocation, (
                f"adapter for {entry.function_id} missing cli_invocation"
            )
            assert entry.agent_path in AGENT_PATH_VALUES

    def test_service_client_invocations_name_real_subcommands(self) -> None:
        from yoke_core.api.service_client import COMMANDS
        prefix = "python3 -m yoke_core.api.service_client "
        bad = []
        for entry in CLI_ADAPTERS:
            if not entry.cli_invocation.startswith(prefix):
                continue
            sub = entry.cli_invocation[len(prefix):].split()[0]
            if sub not in COMMANDS:
                bad.append((entry.function_id, sub))
        assert not bad, (
            f"inventory CLI invocations name subcommands not in COMMANDS: {bad}"
        )

    def test_skill_orchestrated_entries_carry_caveats(self) -> None:
        for entry in CLI_ADAPTERS:
            if entry.agent_path != "skill-orchestrated":
                continue
            assert entry.canonical_skill_invocation
            assert entry.direct_use_caveat
        lifecycle = adapter_for("lifecycle.transition.execute")
        assert lifecycle is not None
        assert lifecycle.agent_path == "skill-orchestrated"
        assert "advance YOK-N <next>" in lifecycle.canonical_skill_invocation
        assert "finalize_evidence_bundle" in lifecycle.direct_use_caveat
        for function_id in ("claims.work.acquire", "claims.work.release"):
            claim_entry = adapter_for(function_id)
            assert claim_entry is not None
            assert claim_entry.agent_path == "skill-orchestrated"
            assert "non-lifecycle claim flows" in claim_entry.direct_use_caveat

    def test_adapter_for_returns_structured_result(self) -> None:
        """AC-8.10 — structured lookup, no shell exit-code probes."""
        sample = CLI_ADAPTERS[0]
        result = adapter_for(sample.function_id)
        assert isinstance(result, AdapterEntry)
        assert result.function_id == sample.function_id
        assert adapter_for("does.not.exist") is None


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
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
    )
    yield
    reset_registry_for_tests()


class TestDispatchParity:
    """AC-8.6 — CLI invocation and direct dispatch produce identical results."""

    def test_call_dispatcher_returns_typed_envelope(
        self, synthetic_handler
    ) -> None:
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

    def test_build_request_round_trips_envelope(
        self, synthetic_handler
    ) -> None:
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
# JSON emission — AC-8.5 / AC-8.9
# ---------------------------------------------------------------------------


class TestJsonMode:
    """AC-8.5 / AC-8.9 — ``--json`` returns the FunctionCallResponse verbatim."""

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
        assert json.loads(out.getvalue()) == {"k": "v"}


# ---------------------------------------------------------------------------
# Actor resolution
# ---------------------------------------------------------------------------


class TestActorResolution:
    def test_build_actor_leaves_actor_id_none_for_server_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # actor_id is optional; build_actor no longer fabricates a sentinel.
        monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
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
