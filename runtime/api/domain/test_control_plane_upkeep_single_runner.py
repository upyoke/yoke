"""One upkeep pass at a time across API worker processes."""

from __future__ import annotations

from yoke_core.domain import control_plane_upkeep as job
from yoke_core.domain import db_helpers
from runtime.api.fixtures.pg_testdb import connect_test_database


def _record_steps(monkeypatch) -> list[str]:
    ran: list[str] = []
    for name in (
        "observe_pending_github_work",
        "replay_settlement_followups",
        "wake_driverless_qa_waits",
        "run_scheduled_prune",
    ):
        monkeypatch.setattr(job, name, lambda _conn, name=name: ran.append(name))
    return ran


def test_a_pass_held_by_another_worker_is_skipped(test_db, monkeypatch):
    ran = _record_steps(monkeypatch)
    dbname = test_db.info.dbname
    with connect_test_database(dbname) as holder, connect_test_database(
        dbname
    ) as upkeep_conn:
        holder.execute("SELECT pg_advisory_lock(%s)", (job.UPKEEP_LOCK_KEY,))
        holder.commit()
        monkeypatch.setattr(db_helpers, "connect", lambda: upkeep_conn)
        job.run_control_plane_upkeep()
        holder.execute("SELECT pg_advisory_unlock(%s)", (job.UPKEEP_LOCK_KEY,))
        holder.commit()
    assert ran == []


def test_a_pass_runs_every_step_and_frees_the_lock(test_db, monkeypatch):
    ran = _record_steps(monkeypatch)
    dbname = test_db.info.dbname
    with connect_test_database(dbname) as upkeep_conn, connect_test_database(
        dbname
    ) as other:
        monkeypatch.setattr(db_helpers, "connect", lambda: upkeep_conn)
        monkeypatch.setattr(upkeep_conn, "close", lambda: None)
        job.run_control_plane_upkeep()
        # The worker's session is still open, yet the next worker can take it.
        taken = other.execute(
            "SELECT pg_try_advisory_lock(%s)", (job.UPKEEP_LOCK_KEY,)
        ).fetchone()[0]
        other.execute("SELECT pg_advisory_unlock(%s)", (job.UPKEEP_LOCK_KEY,))
        other.commit()
    assert ran == [
        "observe_pending_github_work",
        "replay_settlement_followups",
        "wake_driverless_qa_waits",
        "run_scheduled_prune",
    ]
    assert taken is True
