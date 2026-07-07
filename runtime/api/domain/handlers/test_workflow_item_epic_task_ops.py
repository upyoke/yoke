"""Handler coverage for epic task ops and dispatch-chain wrappers."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.handlers import workflow_item_epic_task_ops as handlers
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import (
    list_entries,
    reset_registry_for_tests,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


@contextmanager
def _fake_conn():
    yield object()


def _request(
    function: str,
    *,
    task_num: int | None = 1,
    payload: dict | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="epic_task", epic_id=42, task_num=task_num),
        payload=payload or {},
    )


def test_task_get_returns_legacy_pipe_row() -> None:
    with patch.object(handlers, "_open_connection", _fake_conn):
        with patch.object(handlers.epic, "task_get", return_value="42|1|Task"):
            outcome = handlers.handle_task_get(
                _request("workflow_item.epic_task.get"),
            )

    assert outcome.primary_success
    assert outcome.result_payload == {
        "epic_id": 42,
        "task_num": 1,
        "body": "42|1|Task",
    }


def test_dispatch_chain_update_maps_invalid_field() -> None:
    with patch.object(handlers, "_open_connection", _fake_conn):
        with patch.object(
            handlers.epic, "dispatch_chain_update",
            side_effect=ValueError("invalid field"),
        ):
            outcome = handlers.handle_dispatch_chain_update(
                _request(
                    "workflow_item.epic_dispatch_chain.update",
                    task_num=None,
                    payload={
                        "worktree": "lane-a",
                        "field": "bogus",
                        "value": "x",
                    },
                ),
            )

    assert not outcome.primary_success
    assert outcome.error.code == "invalid_payload"
    assert "invalid field" in outcome.error.message


def test_dispatch_chain_refresh_calls_domain_owner() -> None:
    with patch.object(handlers, "_open_connection", _fake_conn):
        with patch.object(
            handlers.epic,
            "dispatch_chain_refresh_for_activation",
            return_value="refreshed",
        ) as refresh:
            outcome = handlers.handle_dispatch_chain_refresh_activation(
                _request(
                    "workflow_item.epic_dispatch_chain.refresh_activation",
                    task_num=None,
                    payload={"worktree": "lane-a", "task_num": 7},
                ),
            )

    assert outcome.primary_success
    refresh.assert_called_once()
    assert refresh.call_args.args[1:] == ("42", "lane-a", "7")
    assert outcome.result_payload["message"] == "refreshed"


READ_IDS = (
    "workflow_item.epic_task.get",
    "workflow_item.epic_task.simulation_get",
    "workflow_item.epic_dispatch_chain.get",
    "workflow_item.epic_dispatch_chain.list",
)

WRITE_IDS = (
    "workflow_item.epic_task.file_add",
    "workflow_item.epic_task.history_insert",
    "workflow_item.epic_dispatch_chain.update",
    "workflow_item.epic_dispatch_chain.refresh_activation",
)


class TestRegistrationShape:
    @pytest.fixture(autouse=True)
    def _registered(self):
        reset_registry_for_tests()
        register_all_handlers()
        yield
        reset_registry_for_tests()

    def test_reads_need_no_claim_or_side_effects(self) -> None:
        entries = {entry.function_id: entry for entry in list_entries()}
        for fid in READ_IDS:
            assert entries[fid].claim_required_kind is None
            assert entries[fid].side_effects == ()

    def test_writes_require_epic_claim_and_side_effects(self) -> None:
        entries = {entry.function_id: entry for entry in list_entries()}
        for fid in WRITE_IDS:
            assert entries[fid].claim_required_kind == "epic"
            assert entries[fid].side_effects


def test_dispatch_chain_update_denied_without_epic_claim() -> None:
    reset_registry_for_tests()
    register_all_handlers()
    try:
        with patch.object(events_module, "emit_event"), patch.object(
            dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None,
        ), patch.object(
            claims_module, "who_claims_for_item", return_value=None,
        ):
            resp = dispatch(
                _request(
                    "workflow_item.epic_dispatch_chain.update",
                    task_num=None,
                    payload={
                        "worktree": "lane-a",
                        "field": "queue",
                        "value": "[1]",
                    },
                ),
            )
    finally:
        reset_registry_for_tests()

    assert not resp.success
    assert resp.error.code == "claim_required"
