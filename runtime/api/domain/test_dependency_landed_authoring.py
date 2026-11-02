"""New merge waits reject completed landings and preserve future work waits."""

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.dependency_satisfaction import evaluate_satisfaction
from yoke_core.domain.handlers.item_dependency_writes import handle_item_dependency_add
from yoke_core.domain.item_dependency import cmd_dependency_add
from yoke_core.domain.item_dependency_upsert import DependencyAlreadyLandedError
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

LANDING = "2026-01-01T00:00:00Z"


@pytest.fixture
def edge(test_db):
    for item_id in (5, 10):
        insert_item(test_db, id=item_id, workflow_id="dash", status="implementing")
    return test_db, render_item_ref(test_db, 10), render_item_ref(test_db, 5)


def _land(conn, status="release", landing=LANDING):
    conn.execute(
        "UPDATE items SET status=%s, merged_at=%s WHERE id=%s", (status, landing, 5)
    )
    conn.commit()


@pytest.mark.parametrize("status", ["release", "done"])
@pytest.mark.parametrize("gate", ["activation", "integration", "closure"])
def test_new_merge_wait_refuses_landed_blocker_without_writing(edge, status, gate):
    conn, dependent, blocker = edge
    _land(conn, status)
    with pytest.raises(DependencyAlreadyLandedError) as caught:
        cmd_dependency_add(
            conn,
            dependent,
            blocker,
            "dash",
            gate_point=gate,
            satisfaction="fact:merged",
        )
    message = str(caught.value)
    assert message.startswith("dependency_blocker_already_landed:")
    assert blocker in message
    assert "2026-01-01" in message
    assert "No merge dependency is needed" in message
    assert conn.execute("SELECT COUNT(*) FROM item_dependencies").fetchone()[0] == 0


def test_default_integration_merge_wait_returns_named_handler_refusal(edge):
    conn, _, blocker = edge
    _land(conn)
    outcome = handle_item_dependency_add(
        FunctionCallRequest(
            function="items.dependency.add",
            actor=ActorContext(actor_id="op", session_id="test-session"),
            target=TargetRef(kind="item", item_id=10),
            payload={
                "blocking_item": blocker,
                "source": "dash",
                "gate_point": "integration",
                "rationale": "wait for code",
            },
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == DependencyAlreadyLandedError.code
    assert blocker in outcome.error.message
    assert conn.execute("SELECT COUNT(*) FROM item_dependencies").fetchone()[0] == 0


@pytest.mark.parametrize("status", ["implementing", "reviewing-implementation"])
def test_reopened_code_work_can_wait_for_another_landing(edge, status):
    conn, dependent, blocker = edge
    _land(conn, status)
    assert (
        cmd_dependency_add(
            conn, dependent, blocker, "dash", gate_point="integration"
        ).action
        == "created"
    )


@pytest.mark.parametrize("status", ["implementing", "release"])
def test_blocker_without_recorded_landing_can_take_merge_wait(edge, status):
    conn, dependent, blocker = edge
    _land(conn, status, None)
    assert (
        cmd_dependency_add(
            conn, dependent, blocker, "dash", gate_point="integration"
        ).action
        == "created"
    )


def test_existing_edge_keeps_its_clock_and_later_landing_satisfaction(edge):
    conn, dependent, blocker = edge
    first = cmd_dependency_add(
        conn, dependent, blocker, "dash", gate_point="integration"
    )
    created = conn.execute("SELECT created_at FROM item_dependencies").fetchone()[0]
    _land(conn, landing="2099-01-01T00:00:00Z")
    updated = cmd_dependency_add(
        conn,
        dependent,
        blocker,
        "operator",
        gate_point="integration",
        rationale="updated explanation",
    )
    assert updated.action == "updated"
    assert updated.edge.dependency_id == first.edge.dependency_id
    assert (
        conn.execute("SELECT created_at FROM item_dependencies").fetchone()[0]
        == created
    )
    assert evaluate_satisfaction(
        updated.edge.satisfaction,
        "release",
        blocking_merged_at="2099-01-01T00:00:00Z",
        dependency_created_at=created,
        workflow=builtin_workflow_runtime("dash"),
    ).satisfied


@pytest.mark.parametrize(
    "gate,satisfaction",
    [("activation", "status:done"), ("coordination_only", "fact:merged")],
)
def test_completion_waits_and_coordination_records_remain_authorable(
    edge, gate, satisfaction
):
    conn, dependent, blocker = edge
    _land(conn)
    assert (
        cmd_dependency_add(
            conn, dependent, blocker, "dash", gate_point=gate, satisfaction=satisfaction
        ).action
        == "created"
    )
