"""The report and fleet alarm on a host an away session holds (YOK-5511).

Delivery QA found the gap: a session parked on a human gate and then ended
kept its linux-lab lease, and neither the steering report nor the fleet watch
said so, because both read only item-claim holders of live sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.fleet_delta_alarms import DeltaState, idle_holder_alarms
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, session_rows
from yoke_core.domain.steering_fleet_report_test_machines import (
    read_reset_debts,
    reset_debt_lines,
)
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MACHINE = TEST_MACHINE_SETTINGS["resource_name"]


def test_report_alarms_on_a_host_held_by_an_ended_parked_session(
    test_db, tmp_path, monkeypatch
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "gate-parked")
    lease = acquire(test_db, make_qa_admission_target(MACHINE), "gate-parked")
    silent = utc_now() - timedelta(minutes=30)
    test_db.execute(
        "UPDATE harness_sessions SET mode='parked',quiet_reason='HUMAN_GATE',"
        "last_tool_call_at=%s,ended_at=%s WHERE session_id='gate-parked'",
        (silent, silent),
    )
    test_db.commit()

    [row] = read_reset_debts(test_db, 1)

    assert row.test_machine == MACHINE and row.idle_session == "gate-parked"
    assert row.idle_state == "ended"
    assert f"--claim-id {lease.id} --holder-session-id gate-parked" in row.recovery
    [line] = reset_debt_lines((row,))
    assert line.startswith(f"Test Machine {MACHINE}: ALARM held by ended session")
    assert f"upkeep returns it to the queue at {row.returns_at}" in line


def test_a_live_holder_keeps_its_host_out_of_the_alarm(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "walking")
    acquire(test_db, make_qa_admission_target(MACHINE), "walking")
    assert read_reset_debts(test_db, 1) == ()


def test_report_does_not_alarm_on_a_holder_whose_subagent_works(
    test_db, tmp_path, monkeypatch
):
    """The parent exited or parked; its subagent still drives the host."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "subagent-walk")
    acquire(test_db, make_qa_admission_target(MACHINE), "subagent-walk")
    parent = utc_now() - timedelta(hours=2)
    test_db.execute(
        "UPDATE harness_sessions SET mode='parked',quiet_reason='HUMAN_GATE',"
        "last_tool_call_at=%s,native_process_gone_at=%s,last_child_tool_call_at=%s "
        "WHERE session_id='subagent-walk'",
        (parent, parent, utc_now() - timedelta(minutes=3)),
    )
    test_db.commit()
    assert read_reset_debts(test_db, 1) == ()


def test_report_projects_return_from_the_subagent_last_call(
    test_db, tmp_path, monkeypatch
):
    """Stale child activity still alarms, timed from the subagent's last call."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "stale-walk")
    lease = acquire(test_db, make_qa_admission_target(MACHINE), "stale-walk")
    parent = utc_now() - timedelta(hours=5)
    child = utc_now() - timedelta(hours=2)
    test_db.execute(
        "UPDATE work_claims SET claimed_at=%s WHERE id=%s", (parent, lease.id)
    )
    test_db.execute(
        "UPDATE harness_sessions SET mode='parked',quiet_reason='HUMAN_GATE',"
        "last_tool_call_at=%s,last_child_tool_call_at=%s "
        "WHERE session_id='stale-walk'",
        (parent, child),
    )
    test_db.commit()
    [row] = read_reset_debts(test_db, 1)
    assert row.idle_state == "parked"
    assert row.idle_since == format_instant(child)


def test_fleet_alarms_on_an_itemless_parked_host_holder():
    now = datetime(2026, 11, 19, 15, 30, tzinfo=timezone.utc)
    stamp = now - timedelta(minutes=35)
    state = {
        "activity": "silent",
        "intent": {"state": "parked", "reason": "HUMAN_GATE"},
        "next_actor": {"actor": "operator", "reason": "human_gate"},
        "custody": {
            "holds": [{"target_kind": "qa_admission", "target": f"QA_HOST:{MACHINE}"}],
            "qa_hosts": [MACHINE],
        },
    }
    rows = session_rows(
        {
            "rows": [
                {
                    "session_id": "itemless",
                    "session_state": state,
                    "mode": "parked",
                    "last_tool_call_at": stamp,
                    "claims": [],
                }
            ]
        }
    )
    [line] = idle_holder_alarms(FleetSnapshot(now, "seat", sessions=rows), DeltaState())
    assert "ALARM idle-holder session=itemless items=none" in line
    assert f"qa_hosts={MACHINE}" in line


def test_composed_report_carries_the_idle_hold_alarm(test_db, tmp_path, monkeypatch):
    from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
    from yoke_core.domain.steering_fleet_report_render import report_body

    seed_steering_scope(test_db)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "gate-parked")
    acquire(test_db, make_qa_admission_target(MACHINE), "gate-parked")
    silent = utc_now() - timedelta(minutes=30)
    test_db.execute(
        "UPDATE harness_sessions SET mode='parked',quiet_reason='HUMAN_GATE',"
        "last_tool_call_at=%s,native_process_gone_at=%s WHERE session_id='gate-parked'",
        (silent, silent + timedelta(seconds=5)),
    )
    test_db.commit()

    report = compose(test_db)

    assert report.actionable
    body = report_body(report)
    assert f"Test Machine {MACHINE}: ALARM held by exited session gate-parked" in body


def test_a_heartbeat_the_holder_left_before_parking_is_not_work():
    """Delivery QA run-20261120-004: the walk's own last heartbeat, 12s before
    the holder's last tool call, hid a parked, exited holder from the report."""
    from yoke_core.domain.qa_host_idle_hold import holder_away, idle_hold_limit

    own = datetime(2026, 11, 20, 4, 22, tzinfo=timezone.utc)
    row = {
        "live_row": "a", "mode": "parked", "last_tool_call_at": own,
        "native_process_gone_at": own + timedelta(seconds=11),
        "execution_heartbeat_at": own - timedelta(seconds=12),
        "turn_posture": "waiting", "turn_posture_at": own,
    }
    now = own + timedelta(minutes=27)
    assert holder_away(row, now=now, limit=idle_hold_limit()) == "exited"
    row["execution_heartbeat_at"] = now - timedelta(minutes=1)
    assert holder_away(row, now=now, limit=idle_hold_limit()) is None
