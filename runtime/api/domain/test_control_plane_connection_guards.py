"""Every control-plane connection declares the bounds that free its own locks.

A client that hibernates mid-transaction cannot release anything: it is gone.
So the bound belongs on the connection, enforced by the server, and it has to
be there on connections the boot converge never touches -- the protected
ones a production deploy drives, which the converge refuses by design.

The last test is the incident in miniature: a transaction holding a
``deployment_runs`` row goes away, and the row comes free with no operator
terminating a backend by hand.
"""

from __future__ import annotations

from runtime.api.deployment_runs_test_db import db_path as db_path  # noqa: F401

import time

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain import postgres_control_plane_connection as guards
from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.postgres_control_plane_connection import (
    IDLE_IN_TRANSACTION_SESSION_TIMEOUT,
    IDLE_IN_TRANSACTION_SETTING,
    KEEPALIVE_PARAMS,
    guarded_conninfo,
)


#: Bound observation even when the server has failed to enforce the idle timer.
REAP_WAIT_SECONDS = 15.0


def test_a_guarded_dsn_declares_both_bounds() -> None:
    declared = conninfo_to_dict(guarded_conninfo("host=127.0.0.1 dbname=yoke"))

    assert (
        f"-c {IDLE_IN_TRANSACTION_SETTING}={IDLE_IN_TRANSACTION_SESSION_TIMEOUT}"
        in declared["options"]
    )
    for key, value in KEEPALIVE_PARAMS.items():
        assert declared[key] == value


def test_guarding_a_dsn_twice_changes_nothing() -> None:
    """Idempotent, so a guarded DSN reused as input cannot accumulate options."""
    once = guarded_conninfo("host=127.0.0.1 dbname=yoke")

    assert guarded_conninfo(once) == once


def test_a_uri_dsn_is_guarded_too() -> None:
    """URI and key/value forms both reach libpq, so both must carry the bounds."""
    declared = conninfo_to_dict(guarded_conninfo("postgresql://someone@h:5432/yoke"))

    assert declared["dbname"] == "yoke"
    assert IDLE_IN_TRANSACTION_SETTING in declared["options"]
    assert declared["keepalives"] == "1"


def test_values_the_caller_declared_are_kept() -> None:
    """A caller naming its own bound owns it; the guard only fills gaps."""
    declared = conninfo_to_dict(
        guarded_conninfo(
            f"host=h keepalives_idle=99 options='-c {IDLE_IN_TRANSACTION_SETTING}=9min'"
        )
    )

    assert declared["keepalives_idle"] == "99"
    assert f"{IDLE_IN_TRANSACTION_SETTING}=9min" in declared["options"]
    assert "2min" not in declared["options"]


def test_a_connection_from_the_factory_carries_the_bound(db_path: str) -> None:
    """In force on the session itself, not merely persisted as a role default."""
    conn = connect_test_db(db_path)
    try:
        configured = conn.execute(
            f"SELECT current_setting('{IDLE_IN_TRANSACTION_SETTING}')"
        ).fetchone()[0]
    finally:
        conn.close()

    assert configured == IDLE_IN_TRANSACTION_SESSION_TIMEOUT


def _backend_state(conn: psycopg.Connection, pid: int) -> str | None:
    row = conn.execute(
        "SELECT state FROM pg_stat_activity WHERE pid = %s", (pid,)
    ).fetchone()
    conn.rollback()  # pg_stat_activity is snapshotted per transaction
    return row[0] if row else None


def test_an_abandoned_transaction_releases_its_run_row_lock(
    db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported incident, bounded: nobody terminates a backend by hand.

    The bound is shortened to keep the test quick; what is under test is that
    the declared startup option really is what PostgreSQL enforces, and that
    enforcing it frees the run row the abandoned transaction was holding.
    """
    monkeypatch.setattr(guards, "IDLE_IN_TRANSACTION_SESSION_TIMEOUT", "1s")
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)

    abandoned = connect_test_db(db_path)
    waiting = connect_test_db(db_path)
    try:
        # The observer is not the abandoned client. Keep it alive if Windows
        # deschedules the test between a pg_stat_activity read and rollback.
        waiting.execute(f"SET {IDLE_IN_TRANSACTION_SETTING} TO '30s'")
        waiting.commit()
        backend, bound = abandoned.execute(
            f"SELECT pg_backend_pid(), current_setting('{IDLE_IN_TRANSACTION_SETTING}')"
        ).fetchone()
        assert bound == "1s"
        abandoned.execute(
            "SELECT status FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,)
        )
        assert _backend_state(waiting, backend) == "idle in transaction"
        # Nothing on the client's side ends this transaction; only the server's
        # own bound can, which is the whole point.
        deadline = time.monotonic() + REAP_WAIT_SECONDS
        active = _backend_state(waiting, backend)
        while active is not None and time.monotonic() < deadline:
            time.sleep(0.05)
            active = _backend_state(waiting, backend)

        # The server ended that backend on its own; this session lives on, so
        # no crash or restart did it.
        assert active is None, f"backend {backend} survived the idle bound in state {active!r}"
        # POSIX clients still read the FATAL; Windows ones see only the close.
        with pytest.raises(
            (psycopg.errors.IdleInTransactionSessionTimeout, psycopg.OperationalError)
        ):
            abandoned.execute("SELECT 1")
        assert abandoned.closed

        # The lock went with the backend, so the next driver simply proceeds.
        assert lock_run(waiting, run_id) == "created"
    finally:
        waiting.rollback()
        waiting.close()
        abandoned.close()
