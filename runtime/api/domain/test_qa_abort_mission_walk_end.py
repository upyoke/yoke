"""An aborted mission walk keeps its host for cleanup until walk-end settles it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_qa import ACTOR, _request
from runtime.api.domain.test_qa_aborted_mission_review import _recorded_mission
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.machine_qa_mission_walk import execute_agent_mission_walk_end
from yoke_core.domain.project_retirement import set_retirement
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution
from yoke_core.domain.qa_plan_execution_stop import (
    STEERING_STOP_REASON,
    stop_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_plan_review import begin_plan_review

ITEM = 4593
RETIRE = "yoke --env ENV projects retire --project SLUG"


def _walking_mission(test_db: Any, tmp_path: Any, monkeypatch: Any):
    requirement_id, execution_id, run_id = _recorded_mission(
        test_db, tmp_path, monkeypatch, ITEM
    )
    begin_plan_review(test_db, lock_plan_execution(test_db, execution_id))
    test_db.commit()
    execution = lock_plan_execution(test_db, execution_id)
    assert execution["state"] == "walking"
    return requirement_id, execution, run_id


def _access(execution_id: str, requirement_id: int, **payload: Any):
    return handle_agent_mission_access(
        _request(
            "test_machine.mission.access",
            item_id=ITEM,
            execution_id=execution_id,
            requirement_id=requirement_id,
            payload=payload,
        )
    )


def test_steering_abort_keeps_the_lease_until_walk_end_settles_it(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    requirement_id, execution, run_id = _walking_mission(
        test_db, tmp_path, monkeypatch
    )
    execution_id = str(execution["id"])
    lease_id = execution["test_machine_lease_id"]
    stopped = stop_plan_execution(
        test_db,
        execution,
        actor_id="9",
        session_id="steering-session",
        reason="taken over",
    )
    receipt = stopped["stop_request"]
    assert receipt["outcome"] == "stop_requested"
    assert "walk-end" in receipt["next"]
    assert get_claim(test_db, lease_id).is_active
    current = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    assert current["state"] == "walking"
    assert abort_request(current)["reason"].startswith(STEERING_STOP_REASON)

    # Mission access stays for host cleanup and names what the walk still owes.
    walk = _access(execution_id, requirement_id)
    assert walk.primary_success, walk.error
    assert "mission_walk_stopped" in walk.result_payload["stop_notice"]
    assert RETIRE in walk.result_payload["stop_notice"]

    # Server-side retirement needs no lease and works while the host is held.
    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (9033, 'maple-ledger', 'Maple Ledger', 'MAPLE', '2026-10-21')"
    )
    retired = set_retirement(
        test_db, "maple-ledger", retired=True, reason="QA fixture cleanup"
    )
    test_db.commit()
    assert retired["changed"] and get_claim(test_db, lease_id).is_active

    begun = _access(execution_id, requirement_id, cleanup="begin", run_id=run_id)
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    assert begun.result_payload["cleanup_lease"] and contract["lease_id"] == lease_id
    from yoke_core.domain import machine_qa_mission_walk

    monkeypatch.setattr(
        machine_qa_mission_walk,
        "_execution",
        lambda _contract: SimpleNamespace(
            control=FakeHostControl(),
            material=SimpleNamespace(secrets={}),
            reach_baseline=lambda _name: SimpleNamespace(
                ok=True, error_code=None, evidence={}
            ),
        ),
    )
    ended = execute_agent_mission_walk_end(contract)
    finished = _access(
        execution_id,
        requirement_id,
        cleanup="finish",
        run_id=run_id,
        lease_id=lease_id,
        restore=ended["starting_state_restore"],
    )
    assert finished.primary_success, finished.error
    assert not get_claim(test_db, lease_id).is_active
    settled = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    assert settled["state"] == "aborted"
    assert str(settled["release_reason"]).startswith(STEERING_STOP_REASON)


def test_owner_abort_records_the_stop_and_requires_walk_end(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    _requirement_id, execution, _run_id = _walking_mission(
        test_db, tmp_path, monkeypatch
    )
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_walk_end_required"):
        stop_plan_execution(
            test_db,
            execution,
            actor_id=ACTOR.actor_id,
            session_id=ACTOR.session_id,
            reason="owner stop",
        )
    test_db.rollback()
    current = lock_plan_execution(test_db, str(execution["id"]))
    test_db.rollback()
    assert current["state"] == "walking"
    assert abort_request(current)["reason"] == "owner stop"
    assert get_claim(test_db, current["test_machine_lease_id"]).is_active


def test_settled_walk_refusal_names_the_server_cleanup_still_owed(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    requirement_id, execution_id, _run_id = _recorded_mission(
        test_db, tmp_path, monkeypatch, ITEM
    )
    finish_plan_execution(
        test_db,
        lock_plan_execution(test_db, execution_id),
        state="aborted",
        reason="operator stop",
    )
    test_db.commit()
    refused = _access(execution_id, requirement_id)
    assert refused.error is not None
    assert refused.error.code == "agent_mission_access_failed"
    assert RETIRE in refused.error.message
    assert "machine retire" in refused.error.message
    assert "Progress Log" in refused.error.message
