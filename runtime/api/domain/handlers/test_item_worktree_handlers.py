"""Public handler coverage for item-owned worktree lanes."""

from __future__ import annotations

from contextlib import nullcontext

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import PERM_ITEMS_READ, PERM_ITEMS_WRITE
from yoke_core.domain import db_helpers
from yoke_core.domain.function_authz_scope import permission_key_for
from yoke_core.domain.handlers import (
    _register_item_worktrees,
    item_worktrees as handlers,
)
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)
from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION
from yoke_core.domain.yoke_function_registry import RegistryEntry


def _request(
    function_id: str,
    *,
    item_id: int,
    payload: dict,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="item-worktree-handler-test"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _use_test_connection(monkeypatch, test_db) -> None:
    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: nullcontext(test_db),
    )


def _entry(function_id: str, args: tuple, kwargs: dict) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=args[0],
        request_model=args[1],
        response_model=args[2],
        stability=kwargs["stability"],
        owner_module=kwargs["owner_module"],
        target_kinds=tuple(kwargs["target_kinds"]),
        side_effects=tuple(kwargs["side_effects"]),
        emitted_event_names=tuple(kwargs["emitted_event_names"]),
        guardrails=tuple(kwargs["guardrails"]),
        adapter_status=kwargs["adapter_status"],
        claim_required_kind=kwargs["claim_required_kind"],
    )


def test_get_returns_the_active_lane_for_the_requested_role(
    test_db,
    monkeypatch,
) -> None:
    insert_item(test_db, id=941, workflow_id="issue")
    record_item_worktree(
        test_db,
        item_id=941,
        branch="YOK-941",
        path="/tmp/yoke-941",
        lane_role=LANE_IMPLEMENTATION,
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = handlers.handle_get(
        _request(
            "item_worktrees.get",
            item_id=941,
            payload={"lane_role": LANE_IMPLEMENTATION},
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["worktree"]["branch"] == "YOK-941"
    assert outcome.result_payload["worktree"]["path"] == "/tmp/yoke-941"
    assert outcome.result_payload["worktree"]["lane_role"] == LANE_IMPLEMENTATION


def test_release_requires_the_explicit_all_active_selector(test_db) -> None:
    insert_item(test_db, id=942, workflow_id="issue")

    outcome = handlers.handle_release(
        _request(
            "item_worktrees.release",
            item_id=942,
            payload={"reason": "evidence-only-recovery"},
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.all_active"


def test_release_marks_every_active_lane_released(
    test_db,
    monkeypatch,
) -> None:
    insert_item(
        test_db,
        id=943,
        workflow_id="issue",
        status="implemented",
    )
    lane = record_item_worktree(
        test_db,
        item_id=943,
        branch="YOK-943",
        path="/tmp/yoke-943",
        lane_role=LANE_IMPLEMENTATION,
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = handlers.handle_release(
        _request(
            "item_worktrees.release",
            item_id=943,
            payload={
                "all_active": True,
                "reason": "evidence-only-recovery",
                "clean_lane_attestation": {
                    "worktree_id": lane["id"],
                    "branch": lane["branch"],
                    "path": lane["path"],
                    "observed_clean": True,
                },
            },
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "item_id": 943,
        "released_count": 1,
        "released_worktree_ids": [lane["id"]],
        "reason": "evidence-only-recovery",
    }
    assert list_item_worktrees(test_db, 943, active_only=True) == []


def test_release_refuses_an_item_outside_the_recovery_status(
    test_db,
    monkeypatch,
) -> None:
    insert_item(test_db, id=944, workflow_id="issue", status="release")
    record_item_worktree(
        test_db,
        item_id=944,
        branch="YOK-944",
        path="/tmp/yoke-944",
        lane_role=LANE_IMPLEMENTATION,
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = handlers.handle_release(
        _request(
            "item_worktrees.release",
            item_id=944,
            payload={
                "all_active": True,
                "reason": "evidence-only-recovery",
            },
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "recovery_status_invalid"
    assert list_item_worktrees(test_db, 944, active_only=True)


def test_release_refuses_a_stale_clean_lane_attestation(
    test_db,
    monkeypatch,
) -> None:
    insert_item(test_db, id=945, workflow_id="issue", status="implemented")
    record_item_worktree(
        test_db,
        item_id=945,
        branch="YOK-945",
        path="/tmp/yoke-945",
        lane_role=LANE_IMPLEMENTATION,
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = handlers.handle_release(
        _request(
            "item_worktrees.release",
            item_id=945,
            payload={
                "all_active": True,
                "reason": "evidence-only-recovery",
                "clean_lane_attestation": {
                    "worktree_id": 999,
                    "branch": "YOK-945",
                    "path": "/tmp/yoke-945",
                    "observed_clean": True,
                },
            },
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "clean_lane_attestation_stale"
    assert list_item_worktrees(test_db, 945, active_only=True)


def test_release_requires_a_clean_lane_attestation(
    test_db,
    monkeypatch,
) -> None:
    insert_item(test_db, id=946, workflow_id="issue", status="implemented")
    record_item_worktree(
        test_db,
        item_id=946,
        branch="YOK-946",
        path="/tmp/yoke-946",
        lane_role=LANE_IMPLEMENTATION,
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = handlers.handle_release(
        _request(
            "item_worktrees.release",
            item_id=946,
            payload={
                "all_active": True,
                "reason": "evidence-only-recovery",
            },
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "clean_lane_attestation_required"
    assert list_item_worktrees(test_db, 946, active_only=True)


def test_release_refuses_a_free_form_reason(test_db) -> None:
    insert_item(test_db, id=947, workflow_id="issue", status="implemented")

    outcome = handlers.handle_release(
        _request(
            "item_worktrees.release",
            item_id=947,
            payload={
                "all_active": True,
                "reason": "discard-this-lane",
            },
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.reason"


def test_registrar_exposes_read_and_claimed_release_contracts() -> None:
    entries = {}

    class Registry:
        def register(self, function_id, *args, **kwargs):
            entries[function_id] = (args, kwargs)

    _register_item_worktrees.register(Registry())

    get_kwargs = entries["item_worktrees.get"][1]
    release_kwargs = entries["item_worktrees.release"][1]
    merged_kwargs = entries["item_worktrees.release_merged_lane"][1]
    assert get_kwargs["side_effects"] == []
    assert get_kwargs["claim_required_kind"] is None
    assert release_kwargs["side_effects"] == ["item_worktrees_update_state"]
    assert release_kwargs["claim_required_kind"] == "item"
    assert merged_kwargs["claim_required_kind"] is None
    assert "clean_lane_attestation" in release_kwargs["guardrails"]
    assert "evidence_only_status" in release_kwargs["guardrails"]
    assert (
        permission_key_for(_entry("item_worktrees.get", *entries["item_worktrees.get"]))
        == PERM_ITEMS_READ
    )
    assert (
        permission_key_for(
            _entry("item_worktrees.release", *entries["item_worktrees.release"])
        )
        == PERM_ITEMS_WRITE
    )
