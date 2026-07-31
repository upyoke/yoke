"""Registered creation coverage for additional item worktree lanes."""

from __future__ import annotations

from contextlib import nullcontext

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.function_authz_scope import permission_key_for
from yoke_core.domain.handlers import (
    _register_item_worktrees,
    item_worktree_create,
)
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry


def _request(
    item_id: int,
    *,
    lane_role: str | None = None,
    branch: str | None = None,
) -> FunctionCallRequest:
    payload = (
        {"lane_role": lane_role, "branch": branch}
        if lane_role is not None or branch is not None else {}
    )
    return FunctionCallRequest(
        function="item_worktrees.create",
        actor=ActorContext(session_id="item-worktree-create-test"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _use_test_connection(monkeypatch, test_db) -> None:
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))


def _seed_default_lane(
    test_db,
    item_id: int,
    *,
    project: str = "yoke",
) -> None:
    insert_item(
        test_db,
        id=item_id,
        workflow_id="blitz",
        status="refined-idea",
        project=project,
    )
    record_item_worktree(
        test_db,
        item_id=item_id,
        branch=f"YOK-{item_id}",
        path=f"/tmp/YOK-{item_id}",
        lane_role=LANE_WORKER,
    )
    test_db.commit()


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


def test_create_registers_multiple_workers_and_preserves_idempotent_path(
    test_db,
    monkeypatch,
) -> None:
    _seed_default_lane(test_db, 961)
    _use_test_connection(monkeypatch, test_db)

    first = item_worktree_create.handle_create(
        _request(961, lane_role=LANE_WORKER, branch="blitz/docs")
    )
    second = item_worktree_create.handle_create(
        _request(961, lane_role=LANE_WORKER, branch="blitz/tests")
    )
    assert first.primary_success is True
    assert second.primary_success is True
    assert first.result_payload["worktree"]["path"] is None

    materialized = record_item_worktree(
        test_db,
        item_id=961,
        branch="blitz/docs",
        path="/tmp/blitz-docs",
        lane_role=LANE_WORKER,
    )
    test_db.commit()
    retried = item_worktree_create.handle_create(
        _request(961, lane_role=LANE_WORKER, branch="blitz/docs")
    )

    assert retried.primary_success is True
    assert retried.result_payload["worktree"]["id"] == materialized["id"]
    assert retried.result_payload["worktree"]["path"] == "/tmp/blitz-docs"
    assert [
        row["branch"] for row in list_item_worktrees(test_db, 961, active_only=True)
    ] == ["YOK-961", "blitz/docs", "blitz/tests"]


def test_create_allows_the_sole_required_role_as_the_first_lane(
    test_db,
    monkeypatch,
) -> None:
    insert_item(
        test_db,
        id=962,
        workflow_id="blitz",
        status="refined-idea",
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = item_worktree_create.handle_create(
        _request(962, lane_role=LANE_WORKER, branch="blitz/early")
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["worktree"]["branch"] == "blitz/early"
    assert outcome.result_payload["worktree"]["path"] is None


def test_create_without_lane_arguments_ensures_the_default_lane(
    test_db,
    monkeypatch,
) -> None:
    insert_item(
        test_db,
        id=969,
        workflow_id="blitz",
        status="refined-idea",
    )
    _use_test_connection(monkeypatch, test_db)

    first = item_worktree_create.handle_create(_request(969))
    second = item_worktree_create.handle_create(_request(969))

    assert first.primary_success is True
    assert second.primary_success is True
    assert first.result_payload["worktree"] == second.result_payload["worktree"]
    assert first.result_payload["worktree"]["branch"] == "YOK-969"
    assert first.result_payload["worktree"]["lane_role"] == LANE_WORKER


def test_create_without_lane_arguments_ensures_dash_implementation_lane(
    test_db,
    monkeypatch,
) -> None:
    insert_item(
        test_db,
        id=970,
        workflow_id="dash",
        status="idea",
    )
    _use_test_connection(monkeypatch, test_db)

    first = item_worktree_create.handle_create(_request(970))
    second = item_worktree_create.handle_create(_request(970))

    assert first.primary_success is True
    assert second.primary_success is True
    assert first.result_payload["worktree"] == second.result_payload["worktree"]
    assert first.result_payload["worktree"]["branch"] == "YOK-970"
    assert first.result_payload["worktree"]["lane_role"] == LANE_IMPLEMENTATION


def test_create_enforces_terminal_and_pinned_workflow_policy(
    test_db,
    monkeypatch,
) -> None:
    _seed_default_lane(test_db, 963)
    test_db.execute("UPDATE items SET status = %s WHERE id = %s", ("done", 963))
    insert_item(test_db, id=964, workflow_id="issue", status="implementing")
    record_item_worktree(
        test_db,
        item_id=964,
        branch="YOK-964",
        path="/tmp/YOK-964",
        lane_role=LANE_IMPLEMENTATION,
    )
    test_db.commit()
    _use_test_connection(monkeypatch, test_db)

    terminal = item_worktree_create.handle_create(
        _request(963, lane_role=LANE_WORKER, branch="blitz/terminal")
    )
    disallowed = item_worktree_create.handle_create(
        _request(964, lane_role=LANE_WORKER, branch="issue/worker")
    )

    assert terminal.primary_success is False
    assert terminal.error is not None
    assert terminal.error.code == "item_inactive"
    assert disallowed.primary_success is False
    assert disallowed.error is not None
    assert disallowed.error.code == "lane_creation_refused"
    assert "does not allow" in disallowed.error.message


def test_create_refuses_role_branch_and_integration_conflicts(
    test_db,
    monkeypatch,
) -> None:
    _seed_default_lane(test_db, 965)
    _use_test_connection(monkeypatch, test_db)

    role_conflict = item_worktree_create.handle_create(
        _request(965, lane_role=LANE_INTEGRATION, branch="YOK-965")
    )
    first_integration = item_worktree_create.handle_create(
        _request(965, lane_role=LANE_INTEGRATION, branch="blitz/integration")
    )
    second_integration = item_worktree_create.handle_create(
        _request(965, lane_role=LANE_INTEGRATION, branch="blitz/integration-2")
    )
    invalid_branch = item_worktree_create.handle_create(
        _request(965, lane_role=LANE_WORKER, branch="bad branch")
    )

    assert role_conflict.error is not None
    assert "already registered as" in role_conflict.error.message
    assert first_integration.primary_success is True
    assert second_integration.error is not None
    assert "already has active integration branch" in second_integration.error.message
    assert invalid_branch.error is not None
    assert "can't contain spaces" in invalid_branch.error.message


def test_create_rejects_same_project_branch_but_allows_other_projects(
    test_db,
    monkeypatch,
) -> None:
    _seed_default_lane(test_db, 966)
    _seed_default_lane(test_db, 967)
    _seed_default_lane(test_db, 968, project="other")
    _use_test_connection(monkeypatch, test_db)

    first = item_worktree_create.handle_create(
        _request(966, lane_role=LANE_WORKER, branch="shared/worker")
    )
    same_project = item_worktree_create.handle_create(
        _request(967, lane_role=LANE_WORKER, branch="shared/worker")
    )
    other_project = item_worktree_create.handle_create(
        _request(968, lane_role=LANE_WORKER, branch="shared/worker")
    )

    assert first.primary_success is True
    assert same_project.error is not None
    assert "already registered to item 966" in same_project.error.message
    assert other_project.primary_success is True


def test_registrar_requires_an_item_claim_for_creation() -> None:
    entries = {}

    class Registry:
        def register(self, function_id, *args, **kwargs):
            entries[function_id] = (args, kwargs)

    _register_item_worktrees.register(Registry())

    args, kwargs = entries["item_worktrees.create"]
    assert kwargs["side_effects"] == ["item_worktrees_insert"]
    assert kwargs["claim_required_kind"] == "item"
    assert "sole_required_first_lane" in kwargs["guardrails"]
    assert "path_claim_gate" in kwargs["guardrails"]
    assert "pinned_workflow_lane_policy" in kwargs["guardrails"]
    assert (
        permission_key_for(_entry("item_worktrees.create", args, kwargs))
        == PERM_ITEMS_WRITE
    )
