"""Dispatch-path and claim-contract tests for the item flag verbs.

Covers ``yoke items freeze|thaw|block|unblock``: route resolution,
envelope shape, the required ``--reason`` on block, the usage map, and
the dispatcher-side claim contract. The flag verbs carry no dispatcher
claim gate on purpose — it would refuse before the handler could acquire
on the caller's behalf — so the boundary lives in the handler instead
(covered in ``runtime/api/domain/test_items_flag_commands.py``).
``items.scalar.update`` keeps its item-claim gate unchanged.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim


FLAG_FUNCTION_IDS = (
    "items.freeze.run",
    "items.thaw.run",
    "items.block.run",
    "items.unblock.run",
)

_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_dispatch_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={
            "item_id": 1,
            "item_ref": "YOK-1",
            "status": "implementing",
            "frozen": True,
            "blocked": False,
            "blocked_reason": None,
            "changed": True,
        },
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(*argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_dispatch_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


class TestFlagRoutes:
    @pytest.mark.parametrize(
        ("verb", "function_id"),
        (
            ("freeze", "items.freeze.run"),
            ("thaw", "items.thaw.run"),
            ("unblock", "items.unblock.run"),
        ),
    )
    def test_bare_verb_dispatches_with_an_empty_payload(
        self, verb: str, function_id: str,
    ) -> None:
        assert _run("items", verb, "YOK-42") == 0
        request = _CAPTURED_REQUESTS[-1]
        assert request.function == function_id
        assert request.target.kind == "item"
        assert request.target.item_ref == "YOK-42"
        assert request.payload == {}
        assert request.actor.session_id == "test-session"

    def test_block_carries_the_reason(self) -> None:
        assert _run("items", "block", "42", "--reason", "Awaiting sign-off") == 0
        request = _CAPTURED_REQUESTS[-1]
        assert request.function == "items.block.run"
        assert request.payload == {"reason": "Awaiting sign-off"}

    def test_block_without_a_reason_is_a_usage_error(self) -> None:
        assert _run("items", "block", "42") == 2
        assert _CAPTURED_REQUESTS == []

    def test_item_ref_relays_verbatim(self) -> None:
        assert _run("items", "freeze", "not-a-real-ref") == 0
        assert _CAPTURED_REQUESTS[-1].target.item_ref == "not-a-real-ref"

    def test_every_flag_verb_carries_a_usage_line(self) -> None:
        for function_id in FLAG_FUNCTION_IDS:
            assert function_id in ADAPTER_USAGE
            assert ADAPTER_USAGE[function_id].startswith("yoke items ")


class TestFlagClaimContract:
    """The flag verbs are claim-free; every other scalar write is not."""

    @staticmethod
    def _entry(function_id: str) -> Any:
        register_all_handlers()
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None, f"{function_id} is not registered"
        return entry

    @pytest.mark.parametrize("function_id", FLAG_FUNCTION_IDS)
    def test_flag_verbs_require_no_claim(self, function_id: str) -> None:
        assert self._entry(function_id).claim_required_kind is None

    def test_scalar_update_still_requires_the_item_claim(self) -> None:
        assert self._entry("items.scalar.update").claim_required_kind == "item"

    @staticmethod
    def _request(function_id: str) -> FunctionCallRequest:
        return FunctionCallRequest(
            function=function_id,
            actor=ActorContext(actor_id="1", session_id="mine"),
            target=TargetRef(kind="item", item_id=4242),
            payload={},
        )

    @pytest.mark.parametrize("function_id", FLAG_FUNCTION_IDS)
    def test_the_dispatcher_gate_defers_to_the_handler(
        self, function_id: str, monkeypatch,
    ) -> None:
        """No dispatcher refusal — the handler owns the claim decision.

        A dispatcher-level item gate would refuse before the handler
        could acquire for a caller who holds no claim, which is the
        ceremony these verbs remove. The foreign-holder refusal is
        asserted at the handler in test_items_flag_commands.
        """
        monkeypatch.setattr(
            "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
            lambda _item_id: {"id": 7, "session_id": "someone-else"},
        )
        entry = self._entry(function_id)
        assert verify_claim(entry, self._request(function_id)) is None

    def test_a_foreign_session_claim_still_refuses_a_scalar_update(
        self, monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
            lambda _item_id: {"id": 7, "session_id": "someone-else"},
        )
        entry = self._entry("items.scalar.update")
        refusal: Optional[FunctionCallResponse] = verify_claim(
            entry, self._request("items.scalar.update"),
        )
        assert refusal is not None
        error: Dict[str, Any] = refusal.error.model_dump()
        assert error["code"] == "claim_required"
