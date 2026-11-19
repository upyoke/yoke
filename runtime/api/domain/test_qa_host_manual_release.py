"""Manual custody loss and pre-removal walk-end receipts settle QA executions."""

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from runtime.api.domain import (
    agent_mission_cleanup_test_support as mission_support,
)
from runtime.api.domain.qa_member_machine_partitions_test_support import (
    MACHINES,
    _begin,
    _case_begin,
    _seed,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.machine_reset_debt import reset_owed
from yoke_core.domain.coordination_claims import acquire, get_claim
from yoke_core.domain.coordination_claims_operator import operator_release
from yoke_core.domain.handlers.claims_coordination_claim import handle_release
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_abort
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.sessions_lifecycle_claim_release import release_claim_by_id
from yoke_core.domain.work_claim_targets import make_qa_admission_target


removed_mission = mission_support.removed_mission


@pytest.mark.parametrize("removed_mission", [True], indirect=True)
def test_walk_end_recorded_before_removal_releases_review_host(
    test_db, removed_mission
):
    request, _, original = removed_mission
    current = lock_plan_execution(test_db, request.payload["execution_id"])
    assert current["state"] == "aborted"
    assert current["release_reason"] == "deployment-member-removed"
    assert current["test_machine_lease_id"] is None
    assert not get_claim(test_db, original["lease_id"]).is_active


def _holder_release(test_db, monkeypatch, request, lease_id):
    monkeypatch.setattr(
        "yoke_core.domain.handlers.claims_coordination_claim._connect_rw",
        lambda: nullcontext(test_db),
    )
    return handle_release(
        request.model_copy(
            update={
                "function": "claims.coordination_claim.release",
                "payload": {"claim_id": lease_id, "reason": "stop host work"},
            }
        )
    )


def test_holder_release_refuses_while_its_execution_is_live(
    test_db, removed_mission, monkeypatch
):
    request, _, original = removed_mission
    lease_id = original["lease_id"]
    execution_id = request.payload["execution_id"]

    refused = _holder_release(test_db, monkeypatch, request, lease_id)

    assert refused.error.code == "qa_execution_holds_lease"
    message = refused.error.message
    assert f"QA plan execution {execution_id}, which is still walking" in message
    assert "The lease is released when the execution ends" in message
    assert (
        f"`yoke qa plan abort --project yoke --execution-id {execution_id} "
        "--reason TEXT`"
    ) in message
    assert get_claim(test_db, lease_id).is_active
    current = lock_plan_execution(test_db, execution_id)
    assert current["state"] == "walking"
    assert current["test_machine_lease_id"] == lease_id
    assert reset_owed(test_db, original["settings"]["resource_name"]) is None
    test_db.rollback()

    aborted = handle_plan_execution_abort(
        request.model_copy(
            update={
                "function": "qa.plan_execution.abort",
                "target": TargetRef(kind="global", project_id="yoke"),
                "payload": {"execution_id": execution_id, "reason": "stop host work"},
            }
        )
    )
    # A walking mission's abort records the cancellation; its walk-end settles it.
    assert aborted.error.code == "plan_execution_finish_failed"
    assert "qa_abort_walk_end_required" in aborted.error.message
    assert "covering steering seat release the host claim" in aborted.error.message
    current = lock_plan_execution(test_db, execution_id)
    assert abort_request(current) is not None and current["state"] == "walking"
    assert get_claim(test_db, lease_id).is_active


def test_holder_release_without_live_execution_releases(test_db, monkeypatch):
    seed_qa_session(test_db, "holder")
    held = acquire(test_db, make_qa_admission_target("linux-lab"), "holder")
    test_db.commit()
    request = FunctionCallRequest(
        function="claims.coordination_claim.release",
        actor=ActorContext(actor_id="1", session_id="holder"),
        target=TargetRef(kind="global"),
        payload={},
    )

    released = _holder_release(test_db, monkeypatch, request, held.id)

    assert released.primary_success, released.error
    assert not get_claim(test_db, held.id).is_active


@pytest.mark.parametrize("surface", ["steering", "claim-id"])
def test_manual_release_settles_dirty_mission_review(
    test_db, removed_mission, surface
):
    request, _, original = removed_mission
    lease_id = original["lease_id"]
    if surface == "steering":
        operator_release(
            test_db,
            None,
            f"QA_HOST:{original['settings']['resource_name']}",
            "stop host work",
            expected_claim_id=lease_id,
            expected_holder_session_id=request.actor.session_id,
            operator_actor_id=1,
        )
        reason = "operator-override: stop host work"
    else:
        release_claim_by_id(test_db, lease_id, "stop host work")
        reason = "stop host work"
    current = lock_plan_execution(test_db, request.payload["execution_id"])
    assert current["state"] == "aborted"
    assert current["release_reason"] == reason
    assert current["test_machine_lease_id"] is None
    assert not get_claim(test_db, lease_id).is_active
    assert reset_owed(test_db, original["settings"]["resource_name"]) == "fresh-host"


@pytest.mark.parametrize("host_index", [0, 1])
def test_releasing_either_simultaneous_host_settles_the_whole_set(
    test_db, tmp_path, monkeypatch, host_index
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True, driver=MACHINES[1])
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    current = lock_plan_execution(test_db, execution["id"])
    leases = execution_host_leases(test_db, current)
    release_claim_by_id(test_db, leases[host_index].id, "stop host work")
    current = lock_plan_execution(test_db, execution["id"])
    assert current["state"] == "aborted" and current["test_machine_lease_id"] is None
    assert all(not get_claim(test_db, lease.id).is_active for lease in leases)
    assert all(reset_owed(test_db, test_machine) == "fresh-host" for test_machine in MACHINES)


def test_failed_settlement_rolls_back_manual_release(test_db, removed_mission):
    from yoke_core.domain.qa_host_manual_release import release_host_claim

    request, _, original = removed_mission
    with (
        patch(
            "yoke_core.domain.qa_plan_execution_lifecycle.finish_plan_execution",
            side_effect=ValueError("settlement unavailable"),
        ),
        pytest.raises(ValueError, match="settlement unavailable"),
    ):
        release_host_claim(test_db, original["lease_id"], "stop", commit=False)
    assert get_claim(test_db, original["lease_id"]).is_active
    assert reset_owed(test_db, original["settings"]["resource_name"]) is None
    current = lock_plan_execution(test_db, request.payload["execution_id"])
    assert current["state"] == "walking"
    assert current["test_machine_lease_id"] == original["lease_id"]


# An as-is case owes the host's last verified baseline: the fixture's fresh-host reset.
@pytest.mark.parametrize(
    "baseline,owed",
    [(None, "fresh-host"), ("shell-preconfigured", "shell-preconfigured")],
)
def test_manual_release_owes_the_settled_case_baseline(
    test_db, removed_mission, baseline, owed
):
    from yoke_core.domain.qa_plan_execution_store import canonical, roster_digest

    request, _, original = removed_mission
    execution = lock_plan_execution(test_db, request.payload["execution_id"])
    roster = execution["roster"]
    roster[0].update(
        host_baseline=baseline, starting_state="baseline" if baseline else "as_is"
    )
    roster.append(
        {
            **roster[0],
            "runner_id": "worktree_run",
            "method_config": {},
            "host_baseline": None,
        }
    )
    test_db.execute(
        "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s,cursor_ordinal=%s WHERE id=%s",
        (canonical(roster), roster_digest(roster), len(roster), execution["id"]),
    )
    test_db.commit()
    release_claim_by_id(test_db, original["lease_id"], "stop host work")
    assert not get_claim(test_db, original["lease_id"]).is_active
    assert reset_owed(test_db, original["settings"]["resource_name"]) == owed
