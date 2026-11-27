"""Scoped plans queue for a busy or unhealthy host and are woken on their turn."""

from __future__ import annotations

from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from runtime.api.domain.qa_host_health_turns_test_support import (
    ACTOR as ACTOR,
    ITEM_ID as ITEM_ID,
    MACHINE as MACHINE,
    _begin as _begin,
    _notices as _notices,
    _project_id as _project_id,
    _record as _record,
    _wait_state as _wait_state,
)


from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_reset_debt_test_support import verified_reset
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.harness_provider_unavailable import PROVIDER_UNAVAILABLE_ERROR_CODE
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.machine_qa_host_selection import (
    TestMachineHostUnhealthy as HostUnhealthy,
    acquire_test_machine_admission,
)
from yoke_core.domain.machine_qa_plan_case_execution import _waiting_case
from yoke_core.domain.machine_reset_debt import record_reset_owed, reset_command
from yoke_core.domain.qa_host_health import HOST_UNHEALTHY_REASON, host_unhealthy
from yoke_core.domain.qa_host_turns import machine_waiters
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def _plan(conn: Any, tmp_path: Path, monkeypatch: Any) -> tuple[dict, dict]:
    materialize_installer_campaign(conn, item_id=ITEM_ID)
    configure_test_machine(conn, tmp_path, monkeypatch)
    seed_registered_qa_launch(conn, ACTOR.session_id, actor_id=int(ACTOR.actor_id))
    execution = begin_plan_execution(
        conn,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    return execution, execution["roster"][0]


def test_health_ignores_reset_receipts_without_owed_debt(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    assert host_unhealthy(test_db, MACHINE) is None
    _record(test_db, "verify", "error", "baseline_probe_failed")
    assert host_unhealthy(test_db, MACHINE)["error_code"] == "baseline_probe_failed"
    _record(test_db, "reset", "verified")
    _record(test_db, "golden_capture", "error", "baseline_probe_failed")
    assert host_unhealthy(test_db, MACHINE) is not None
    _record(test_db, "golden_capture", "verified")
    assert host_unhealthy(test_db, MACHINE) is None
    _record(test_db, "reset", "error", "test_machine_sign_in_app_quit_not_proved")
    assert host_unhealthy(test_db, MACHINE) is None


def test_failed_owed_reset_blocks_qa_and_waiter_wake_until_reset(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    execution, case = _plan(test_db, tmp_path, monkeypatch)
    notices = _notices(monkeypatch)
    seed_qa_session(test_db, ACTOR.session_id, "operator")
    _record(test_db, "verify", "verified")
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "operator")
    record_reset_owed(
        test_db, case={"host_baseline": "fresh-host"},
        test_machine=MACHINE, lease_id=held.id,
    )
    assert host_unhealthy(test_db, MACHINE) is None
    assert _begin(execution, case)["state"] == "waiting"
    _record(test_db, "reset", "error", "machine_fixture_failed")
    release(test_db, held.id, "test-machine-reset-failed")

    assert active_claim(test_db, target) is None
    assert _wait_state(test_db, ACTOR.session_id) == "waiting"
    assert notices == []
    command = reset_command(MACHINE, "fresh-host")
    waiting = _begin(execution, case)
    assert waiting["state"] == "waiting"
    assert "machine_fixture_failed" in waiting["host_wait"]["rationale"]
    assert command in waiting["host_wait"]["rationale"]
    for explicit in (None, MACHINE):
        with pytest.raises(HostUnhealthy, match="machine_fixture_failed") as refusal:
            acquire_test_machine_admission(
                test_db, project="yoke", session_id=ACTOR.session_id,
                test_machine=explicit, select_any=True, cases=(case,),
            )
        assert command in str(refusal.value)

    healing = acquire_test_machine_admission(
        test_db, project="yoke", session_id="operator", test_machine=MACHINE,
        select_any=False, require_verified=False,
    )
    _record(test_db, "verify", "verified")
    assert host_unhealthy(test_db, MACHINE) is not None
    verified_reset(test_db, MACHINE, "fresh-host")
    release(test_db, healing.lease.id, "test-machine-reset-complete")

    assert host_unhealthy(test_db, MACHINE) is None
    assert active_claim(test_db, target).session_id == ACTOR.session_id
    assert len(notices) == 1 and "QA host turn ready" in notices[0]
    begin_plan_execution(
        test_db,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    assert _begin(execution, case)["state"] == "ready"


def test_transient_owed_reset_still_wakes_waiter_for_retry(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    execution, case = _plan(test_db, tmp_path, monkeypatch)
    notices = _notices(monkeypatch)
    seed_qa_session(test_db, ACTOR.session_id, "operator")
    _record(test_db, "verify", "verified")
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "operator")
    record_reset_owed(
        test_db, case={"host_baseline": "fresh-host"},
        test_machine=MACHINE, lease_id=held.id,
    )
    assert _begin(execution, case)["state"] == "waiting"
    _record(test_db, "reset", "error", PROVIDER_UNAVAILABLE_ERROR_CODE)
    release(test_db, held.id, "test-machine-reset-provider-unavailable")

    assert host_unhealthy(test_db, MACHINE) is None
    assert active_claim(test_db, target).session_id == ACTOR.session_id
    assert len(notices) == 1 and "QA host turn ready" in notices[0]
    begin_plan_execution(
        test_db,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    ready = _begin(execution, case)
    assert ready["state"] == "ready"
    assert ready["execution"]["reset_owed_baseline"] == "fresh-host"


def test_leased_host_queues_the_plan_and_release_hands_it_the_turn(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    execution, case = _plan(test_db, tmp_path, monkeypatch)
    notices = _notices(monkeypatch)
    seed_qa_session(test_db, ACTOR.session_id, "holder")
    target = make_qa_admission_target(MACHINE)
    held = acquire(test_db, target, "holder")

    waiting = _begin(execution, case)
    assert waiting["state"] == "waiting"
    assert waiting["host_wait"]["position"] == 1
    assert waiting["host_wait"]["test_machine"] == MACHINE
    assert "Park until then" in waiting["lease_context"]["wait_message"]

    release(test_db, held.id, "holder-finished")
    assert active_claim(test_db, target).session_id == ACTOR.session_id
    assert len(notices) == 1 and "QA host turn ready" in notices[0]

    begin_plan_execution(
        test_db,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    assert _begin(execution, case)["state"] == "ready"
    assert _wait_state(test_db, ACTOR.session_id) == "granted"


def test_unhealthy_host_queues_until_a_golden_capture_heals_it(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    execution, case = _plan(test_db, tmp_path, monkeypatch)
    notices = _notices(monkeypatch)
    seed_qa_session(test_db, ACTOR.session_id, "ended-waiter", "operator")
    _record(test_db, "verify", "error", "baseline_probe_failed")
    target = make_qa_admission_target(MACHINE)

    waiting = _begin(execution, case)
    assert waiting["state"] == "waiting"
    assert HOST_UNHEALTHY_REASON in waiting["host_wait"]["rationale"]
    rationale = waiting["host_wait"]["rationale"]
    assert f"QA must wait to acquire {MACHINE}" in rationale
    assert "baseline_probe_failed" in rationale
    assert "yoke test-machine verify" in rationale
    assert "Keep the sealed baseline unchanged" in rationale
    assert "golden-capture" not in rationale
    assert active_claim(test_db, target) is None
    assert notices == []

    # An ended session drops out: the healed host passes over it.
    test_db.execute(
        "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,"
        "state,resume_command,rationale) VALUES(%s,%s,'ended-waiter',1,"
        "now() - interval '1 hour','waiting','yoke qa plan run','queued')",
        (str(uuid4()), MACHINE),
    )
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=now() WHERE session_id='ended-waiter'"
    )
    test_db.commit()
    assert [row["session_id"] for row in machine_waiters(test_db, MACHINE)] == [
        ACTOR.session_id
    ]

    # The operator's own heal is admitted, then its release serves the line.
    healing = acquire(test_db, target, "operator")
    _record(test_db, "golden_capture", "verified")
    release(test_db, healing.id, "test-machine-golden-capture-complete")

    assert active_claim(test_db, target).session_id == ACTOR.session_id
    assert _wait_state(test_db, ACTOR.session_id) == "reserved"
    assert len(notices) == 1 and "QA host turn ready" in notices[0]


def test_failed_heal_keeps_the_line_waiting(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    execution, case = _plan(test_db, tmp_path, monkeypatch)
    notices = _notices(monkeypatch)
    seed_qa_session(test_db, ACTOR.session_id, "operator")
    _record(test_db, "verify", "error", "baseline_probe_failed")
    target = make_qa_admission_target(MACHINE)
    assert _begin(execution, case)["state"] == "waiting"

    healing = acquire(test_db, target, "operator")
    _record(test_db, "verify", "error", "baseline_probe_failed")
    release(test_db, healing.id, "test-machine-verify-complete")

    assert active_claim(test_db, target) is None
    assert _wait_state(test_db, ACTOR.session_id) == "waiting"
    assert notices == []


def test_waiting_case_teaches_queue_position_and_park() -> None:
    case = _waiting_case(
        {
            "host_wait": {
                "test_machine": "linux-lab",
                "position_text": "2nd for linux-lab",
                "rationale": "lease 9 held by holder",
            }
        },
        7,
        runner_id="host_control",
    )
    assert case["verdict"] == "waiting"
    assert case["recovery"].startswith(
        "Queued for QA host linux-lab, 2nd for linux-lab (lease 9 held by holder)."
    )
    assert "yoke sessions touch --mode parked" in case["recovery"]
    assert "Write no hold" in case["recovery"]
    # An older server sends no host_wait; the case still teaches the park.
    assert (
        "Queued for QA host its Test Machine."
        in (_waiting_case({}, 7, runner_id="agent_mission")["recovery"])
    )
