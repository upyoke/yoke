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
from yoke_contracts.timestamps import utc_now
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
    assert f"upkeep returns it to the line at {row.returns_at}" in line


def test_a_live_holder_keeps_its_host_out_of_the_alarm(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "walking")
    acquire(test_db, make_qa_admission_target(MACHINE), "walking")
    assert read_reset_debts(test_db, 1) == ()


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
