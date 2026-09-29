"""Every control-plane connection declares the bounds that free its own locks.

A client that hibernates mid-transaction cannot release anything: it is gone.
So the bound belongs on the connection, enforced by the server, and it has to
be there on connections the boot converge never touches -- the prod-flagged
ones a production deploy drives, which the converge refuses by design.

The last test is the incident in miniature: a transaction holding a
``deployment_runs`` row goes away, and the row comes free with no operator
terminating a backend by hand.
"""

from __future__ import annotations

import time

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain import postgres_control_plane_connection as guards
from yoke_core.domain.deployment_runs_lock import lock_run_bounded
from yoke_core.domain.postgres_control_plane_connection import (
    IDLE_IN_TRANSACTION_SESSION_TIMEOUT,
    IDLE_IN_TRANSACTION_SETTING,
    KEEPALIVE_PARAMS,
    guarded_conninfo,
)

pytest_plugins = ["runtime.api.deployment_runs_test_db"]

#: Well past the shortened bound the reaping test declares, so a loaded cluster
#: cannot make it flake.
REAP_WAIT_SECONDS = 4.0


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
            "host=h keepalives_idle=99 "
            f"options='-c {IDLE_IN_TRANSACTION_SETTING}=9min'"
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
        abandoned.execute(
            "SELECT status FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,)
        )
        # Nothing on the client's side ends this transaction; only the server's
        # own bound can, which is the whole point.
        time.sleep(REAP_WAIT_SECONDS)

        with pytest.raises(psycopg.errors.IdleInTransactionSessionTimeout) as raised:
            abandoned.execute("SELECT 1")
        assert "idle-in-transaction timeout" in str(raised.value)

        # The lock went with the backend, so the next driver simply proceeds.
        assert lock_run_bounded(waiting, run_id) == "created"
    finally:
        waiting.rollback()
        waiting.close()
        abandoned.close()
