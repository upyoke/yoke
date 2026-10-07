"""A deploy driver's liveness writes refuse a busy run row instead of queueing.

The driver attachment is bookkeeping about whether this process is still alive.
Waiting for it is therefore self-defeating: a heartbeat queued behind another
transaction stops reporting the very liveness it exists to report, and the
watcher that reads its stream has nothing else to print. Worse, the release on
shutdown queues the same way, so a process asked to stop cannot.

Both sides here take the run row under a bounded lock and refuse by name --
holder pid, age and state -- leaving the caller's transaction intact.
"""

from __future__ import annotations

import time

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    attach_driver,
    release_driver,
)
from yoke_core.domain.deployment_runs_lock import (
    RUN_ROW_LOCK_BLOCKED_PREFIX,
    RUN_ROW_LOCK_TIMEOUT_MS,
    DeploymentRunRowLockBusy,
    lock_run_bounded,
)

pytest_plugins = ["runtime.api.deployment_runs_test_db"]

NOW = "2026-09-21T12:00:00Z"

#: Generous enough that a loaded shared cluster cannot flake it, far below the
#: unbounded wait this replaces -- the reported stall ran past eleven minutes.
PROMPT_SECONDS = 30.0


def _hold_run_row(conn, run_id: str) -> None:
    """Lock the run row and stay in the transaction, as an abandoned client does."""
    conn.execute("SELECT status FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,))


def test_attach_refuses_a_run_row_another_transaction_holds(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    holder = connect_test_db(db_path)
    driver = connect_test_db(db_path)
    try:
        _hold_run_row(holder, run_id)

        started = time.monotonic()
        with pytest.raises(DeploymentRunRowLockBusy) as raised:
            attach_driver(
                driver,
                run_id,
                session_id="sess-driver",
                pid=4242,
                phase=PHASE_EXECUTING,
                now=NOW,
            )
        elapsed = time.monotonic() - started

        assert elapsed >= RUN_ROW_LOCK_TIMEOUT_MS / 1000
        assert elapsed < PROMPT_SECONDS
        text = str(raised.value)
        assert text.startswith(RUN_ROW_LOCK_BLOCKED_PREFIX)
        assert run_id in text
        # The holder is named, and named as abandoned rather than busy.
        assert "idle in transaction" in text
        assert f"yoke watch deploy -- {run_id}" in text
    finally:
        holder.rollback()
        holder.close()
        driver.close()


def test_a_refused_lock_leaves_the_callers_transaction_usable(db_path: str) -> None:
    """The savepoint rolls back the failed lock and nothing else.

    Without it the lock timeout would poison the whole transaction, and the
    refusal could not even read the holder it names.
    """
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    holder = connect_test_db(db_path)
    driver = connect_test_db(db_path)
    try:
        driver.execute("SELECT 1")
        _hold_run_row(holder, run_id)

        with pytest.raises(DeploymentRunRowLockBusy):
            lock_run_bounded(driver, run_id)

        assert driver.execute("SELECT 1").fetchone()[0] == 1
    finally:
        holder.rollback()
        holder.close()
        driver.close()


def test_release_refuses_a_busy_row_so_shutdown_always_completes(
    db_path: str,
) -> None:
    """The reported failure: SIGTERM left the watcher stuck in its own release."""
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    driver = connect_test_db(db_path)
    holder = connect_test_db(db_path)
    try:
        attached = attach_driver(
            driver,
            run_id,
            session_id="sess-driver",
            pid=4242,
            phase=PHASE_EXECUTING,
            now=NOW,
        )
        driver.commit()
        assert attached is not None

        _hold_run_row(holder, run_id)

        started = time.monotonic()
        with pytest.raises(DeploymentRunRowLockBusy) as raised:
            release_driver(driver, run_id, session_id="sess-driver", pid=4242)
        elapsed = time.monotonic() - started

        assert elapsed < PROMPT_SECONDS
        assert str(raised.value).startswith(RUN_ROW_LOCK_BLOCKED_PREFIX)
    finally:
        holder.rollback()
        holder.close()
        driver.close()


def test_an_uncontended_row_still_locks_and_reports_its_status(db_path: str) -> None:
    """The bound narrows nothing when the row is free."""
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        assert lock_run_bounded(conn, run_id) == "created"
        assert lock_run_bounded(conn, "run-does-not-exist") is None
    finally:
        conn.rollback()
        conn.close()


def _hold_run_table_for_creation(conn) -> None:
    """Hold the table as run creation once did: SHARE ROW EXCLUSIVE, open."""
    conn.execute("LOCK TABLE deployment_runs IN SHARE ROW EXCLUSIVE MODE")


@pytest.mark.parametrize("operation", ["attach", "release"])
def test_a_table_lock_that_blocks_the_write_refuses_by_name(
    db_path: str, operation: str
) -> None:
    """The row lock came free but the write did not, and that escaped raw.

    ``FOR UPDATE`` holds the table in ROW SHARE mode, which a SHARE ROW
    EXCLUSIVE holder does not block, so the row lock succeeded and the
    following ``UPDATE`` waited for ROW EXCLUSIVE outside the bound. Its lock
    timeout surfaced as a ``LockNotAvailable`` traceback that killed the deploy
    watcher before its exit sentinel.
    """
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    driver = connect_test_db(db_path)
    holder = connect_test_db(db_path)
    try:
        attach_driver(
            driver,
            run_id,
            session_id="sess-driver",
            pid=4242,
            phase=PHASE_EXECUTING,
            now=NOW,
        )
        driver.commit()
        _hold_run_table_for_creation(holder)

        with pytest.raises(DeploymentRunRowLockBusy) as raised:
            if operation == "attach":
                attach_driver(
                    driver,
                    run_id,
                    session_id="sess-driver",
                    pid=4242,
                    phase=PHASE_EXECUTING,
                    now=NOW,
                )
            else:
                release_driver(driver, run_id, session_id="sess-driver", pid=4242)

        assert str(raised.value).startswith(RUN_ROW_LOCK_BLOCKED_PREFIX)
        assert driver.execute("SELECT 1").fetchone()[0] == 1
    finally:
        holder.rollback()
        holder.close()
        driver.rollback()
        driver.close()


def test_run_creation_leaves_other_runs_writable(
    db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creation serializes against creation, not against every run write.

    Composition validation runs inside the creating transaction and can take
    seconds; the driver of a run already executing must still heartbeat then.
    """
    from yoke_core.domain import deployment_runs_validation as validation

    running = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    real_validate = validation.cmd_validate_composition
    attached_during_create: list[bool] = []

    def _validate_while_a_driver_heartbeats(*args, **kwargs):
        other = connect_test_db(db_path)
        try:
            recorded = attach_driver(
                other,
                running,
                session_id="sess-driver",
                pid=4242,
                phase=PHASE_EXECUTING,
                now=NOW,
            )
            other.commit()
            attached_during_create.append(recorded is not None)
        finally:
            other.close()
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(
        validation, "cmd_validate_composition", _validate_while_a_driver_heartbeats
    )

    created = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)

    assert created != running
    assert attached_during_create == [True]
