"""Failed host restoration can recover through a same-lease reset receipt."""

from runtime.api.domain.qa_abort_reset_test_support import (
    failed_restore as failed_restore,
    operation as operation,
)


import json
from datetime import timedelta

import pytest

from runtime.api.domain.machine_qa_plan_execution_test_support import (
    ACTOR,
    _active_lease_count,
)
from yoke_contracts.api.function_call import (
    ActorContext,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.qa_plan_execution_state import (
    finish_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_plan_execution_abort_state import (
    abort_request,
    host_cleanup_proven,
)


@pytest.mark.parametrize("steering", [False, True])
def test_reset_then_abort_settles_normal_terminal_path(
    test_db, failed_restore, monkeypatch, steering
):
    execution = failed_restore
    actor = ACTOR
    if steering:
        actor = ActorContext(actor_id="1", session_id="covering-steering")
        monkeypatch.setattr(
            "yoke_core.domain.session_steering_authority.covering_session_seat",
            lambda *a, **kw: {"session_id": actor.session_id},
        )
    begun = handle_operation_begin(operation(actor))
    assert begun.primary_success, begun.error
    issued = begun.result_payload["execution"]
    assert issued["lease_id"] == execution["test_machine_lease_id"]
    submitted = handle_operation_submit(
        operation(
            actor,
            lease_id=issued["lease_id"],
            contract_digest=issued["contract_digest"],
            status="verified",
            checks=[{"name": "fresh-host", "ok": True}],
        )
    )
    assert submitted.primary_success, submitted.error
    assert _active_lease_count(test_db) == 1
    execution = lock_plan_execution(test_db, execution["id"])
    assert host_cleanup_proven(test_db, execution, 0)
    finish_plan_execution(test_db, execution, state="aborted", reason="recovered host")
    assert execution["state"] == "aborted"
    assert _active_lease_count(test_db) == 0
    assert not test_db.execute(
        "SELECT 1 FROM qa_runs WHERE qa_requirement_id=%s AND execution_status='captured'",
        (execution["roster"][0]["requirement_id"],),
    ).fetchone()


@pytest.mark.parametrize(
    "change",
    [
        "stale",
        "failed",
        "wrong_baseline",
        "wrong_lease",
        "wrong_machine",
    ],
)
def test_unrelated_or_failed_reset_cannot_settle_abort(test_db, failed_restore, change):
    from yoke_core.domain.machine_operation_recording import (
        record_test_machine_operation,
    )
    from yoke_core.domain.machine_qa_execution_protocol import _issue
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.host_control_runner import load_test_machine_contract

    execution = failed_restore
    lease = get_claim(test_db, execution["test_machine_lease_id"])
    test_machine = lease.target.test_machine
    candidate = load_test_machine_contract(test_db, project="yoke", test_machine=test_machine)
    contract = _issue(
        test_db,
        candidate,
        lease,
        operation="reset",
        checks=(),
        baselines=["fresh-host"],
        cases=(),
    )
    if change == "wrong_machine":
        from yoke_core.domain.machine_qa_capability import replace_test_machine_settings

        replace_test_machine_settings(
            test_db,
            project="yoke",
            test_machine="other-host",
            base_settings=None,
            settings={**candidate.settings, "resource_name": "other-host"},
        )
    record_test_machine_operation(
        test_db,
        candidate.project_id,
        test_machine="other-host" if change == "wrong_machine" else test_machine,
        operation="reset",
        status="error" if change == "failed" else "verified",
        checks=[
            {
                "name": "shell-preconfigured"
                if change == "wrong_baseline"
                else "fresh-host",
                "ok": change != "failed",
            }
        ],
        error_code="reset_failed" if change == "failed" else None,
        lease_id=lease.id + 1 if change == "wrong_lease" else lease.id,
        contract_digest=contract.contract_digest,
    )
    if change == "stale":
        test_db.execute(
            "UPDATE test_machine_operation_receipts SET performed_at=%s",
            (utc_now() - timedelta(days=1),),
        )
        test_db.commit()
    assert not host_cleanup_proven(test_db, execution, 0)
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_restore_pending"):
        finish_plan_execution(
            test_db, execution, state="aborted", reason="still not restored"
        )
    assert _active_lease_count(test_db) == 1


@pytest.mark.parametrize(
    "op,baseline", [("verify", "fresh-host"), ("reset", "shell-preconfigured")]
)
def test_pending_abort_only_allows_declared_reset(
    test_db, failed_restore, op, baseline
):
    result = handle_operation_begin(operation(ACTOR, op, baseline=baseline))
    assert not result.primary_success
    assert "qa_abort_reset_required" in result.error.message


def test_foreign_session_without_covering_seat_cannot_reset(
    test_db, failed_restore, monkeypatch
):
    monkeypatch.setattr(
        "yoke_core.domain.session_steering_authority.covering_session_seat",
        lambda *a, **kw: None,
    )
    result = handle_operation_begin(
        operation(ActorContext(actor_id="1", session_id="foreign-session"))
    )
    assert not result.primary_success
    assert "qa_abort_reset_authority_required" in result.error.message


def test_existing_abort_requires_durable_request_time_before_reset(
    test_db, failed_restore
):
    from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON

    execution = failed_restore
    checkpoint = json.loads(execution["release_reason"][len(PAUSE_REASON) :])
    checkpoint["abort"].pop("requested_at")
    execution["release_reason"] = PAUSE_REASON + json.dumps(checkpoint)
    test_db.execute(
        "UPDATE qa_plan_executions SET release_reason=%s WHERE id=%s",
        (execution["release_reason"], execution["id"]),
    )
    test_db.commit()
    refused = handle_operation_begin(operation(ACTOR))
    assert not refused.primary_success
    assert "qa_abort_reset_checkpoint_required" in refused.error.message
    execution = lock_plan_execution(test_db, execution["id"])
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_restore_pending"):
        finish_plan_execution(
            test_db, execution, state="aborted", reason="retry cancellation"
        )
    assert abort_request(execution)["requested_at"]
    ready = handle_operation_begin(operation(ACTOR))
    assert ready.primary_success, ready.error
