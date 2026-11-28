"""A QA host owner that exited between turns reads as paused, not lost (YOK-5785).

Feedback 98989: a Lab 2 owner finished its native turn with exit 0 and stayed
wakeable while its walk waited on a publication, yet the report alarmed
"held by exited session" and offered a release. A resumable pause names the
pause and the same idle deadline; a truly ended owner keeps its alarm.
"""

from __future__ import annotations

from datetime import timedelta

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.qa_host_idle_hold import (
    held_rows,
    holder_away,
    idle_hold_limit,
    release_idle_host_holds,
)
from yoke_core.domain.steering_fleet_report_test_machines import (
    read_reset_debts,
    reset_debt_lines,
)
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MACHINE = TEST_MACHINE_SETTINGS["resource_name"]
#: A codex-cli version whose capability proves a resume from the transcript.
RESUMABLE_VERSION = "0.200.0"


def _exited_holder(conn, session_id, *, silent_for, origin="yoke", ended=False):
    seed_qa_session(conn, session_id)
    lease = acquire(conn, make_qa_admission_target(MACHINE), session_id)
    silent = utc_now() - silent_for
    conn.execute(
        "UPDATE work_claims SET claimed_at=%s WHERE id=%s", (silent, lease.id)
    )
    conn.execute(
        "UPDATE harness_sessions SET mode='wait',executor_surface='codex-cli',"
        "launch_origin=%s,executor_version=%s,last_tool_call_at=%s,"
        "native_process_gone_at=%s,ended_at=%s WHERE session_id=%s",
        (
            origin,
            RESUMABLE_VERSION,
            silent,
            silent + timedelta(seconds=5),
            silent + timedelta(seconds=6) if ended else None,
            session_id,
        ),
    )
    conn.commit()
    return lease


def test_a_wakeable_exit_reads_as_a_pause_with_its_deadline(
    test_db, tmp_path, monkeypatch
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _exited_holder(test_db, "between-turns", silent_for=timedelta(minutes=20))

    [row] = read_reset_debts(test_db, 1)

    assert row.idle_state == "exited" and row.recovery is None
    [line] = reset_debt_lines((row,))
    assert line.startswith(
        f"Test Machine {MACHINE}: held by session between-turns, paused between turns"
    )
    assert "resumes on its next message" in line
    assert f"returns the host to the queue at {row.returns_at}" in line
    assert "ALARM" not in line and "release" not in line


def test_an_exit_that_cannot_resume_keeps_the_alarm(test_db, tmp_path, monkeypatch):
    """An operator-launched surface is never resumed by Yoke."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    lease = _exited_holder(
        test_db, "desk-exit", silent_for=timedelta(minutes=20), origin="operator"
    )

    [row] = read_reset_debts(test_db, 1)

    assert f"--claim-id {lease.id} --holder-session-id desk-exit" in row.recovery
    [line] = reset_debt_lines((row,))
    assert line.startswith(f"Test Machine {MACHINE}: ALARM held by exited session")
    assert f"workaround=`{row.recovery}`" in line


def test_a_truly_ended_owner_keeps_its_recovery(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _exited_holder(test_db, "gone-for-good", silent_for=timedelta(minutes=20), ended=True)

    [row] = read_reset_debts(test_db, 1)

    assert row.idle_state == "ended" and row.recovery
    [line] = reset_debt_lines((row,))
    assert line.startswith(f"Test Machine {MACHINE}: ALARM held by ended session")


def test_the_pause_wording_leaves_upkeep_unchanged(test_db, tmp_path, monkeypatch):
    """A paused owner still counts as away and is returned at the same limit."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    limit = idle_hold_limit()
    lease = _exited_holder(test_db, "long-pause", silent_for=limit + timedelta(minutes=1))
    [row] = held_rows(test_db)
    assert holder_away(row, now=utc_now(), limit=limit) == "exited"

    assert release_idle_host_holds(test_db) == [lease.id]
    assert not any(
        getattr(debt, "idle_session", None) for debt in read_reset_debts(test_db, 1)
    )
