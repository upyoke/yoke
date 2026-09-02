"""PostgreSQL transaction guards for dispatch waits and application roles."""

from __future__ import annotations

import concurrent.futures
from types import SimpleNamespace
from unittest.mock import patch

import psycopg

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.postgres_application_role_settings import (
    APPLICATION_ROLE_DEFAULT_NOT_PERSISTED,
    IDLE_IN_TRANSACTION_SESSION_TIMEOUT,
    converge_application_role_settings,
)
from yoke_core.domain.yoke_function_dispatch_idempotency import (
    request_reservation,
)
from runtime.api.fixtures import pg_testdb


def _deny_statements_containing(conn, fragment, error):
    """Raise *error* for statements containing *fragment*, passing others through."""
    real = conn.execute

    def execute(statement, *args, **kwargs):
        if fragment in str(statement):
            raise error
        return real(statement, *args, **kwargs)

    return execute


def test_relay_request_reservation_is_transaction_free_while_handler_waits() -> None:
    """The reservation surrounds the relay claim's long-poll handler."""
    reservation = db_helpers.connect()
    observer = db_helpers.connect()
    entry = SimpleNamespace(
        side_effects=("session_control_jobs_lease",),
        guardrails=(),
    )
    request = FunctionCallRequest(
        function="session_control.relay.claim",
        request_id="relay-long-poll",
        actor=ActorContext(actor_id="1", session_id="relay-session"),
        target=TargetRef(kind="global"),
        payload={},
    )

    try:
        with patch(
            "yoke_core.domain.control_plane_transport.local_connection_or_none",
            return_value=reservation,
        ):
            with request_reservation(entry, request):
                row = observer.execute(
                    "SELECT state, xact_start FROM pg_stat_activity WHERE pid=%s",
                    (reservation.info.backend_pid,),
                ).fetchone()
                assert row == ("idle", None)
    finally:
        observer.close()


def test_application_role_declares_bounded_idle_transaction_timeout(
    cluster_role_authority,
) -> None:
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        with psycopg.connect(dsn) as conn:
            converge_application_role_settings(conn)

        with psycopg.connect(dsn) as conn:
            configured = conn.execute(
                "SELECT current_setting('idle_in_transaction_session_timeout')"
            ).fetchone()[0]

        assert configured == IDLE_IN_TRANSACTION_SESSION_TIMEOUT
    finally:
        pg_testdb.drop_test_database(database, pooled=False)


def test_application_role_default_persists_once_and_then_skips_the_catalog(
    capsys,
    cluster_role_authority,
) -> None:
    """The steady state performs no catalog write, so concurrent boots cannot race."""
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        with psycopg.connect(dsn) as conn:
            converge_application_role_settings(conn)
            conn.commit()

        with psycopg.connect(dsn) as conn:
            with patch.object(conn, "execute", wraps=conn.execute) as executed:
                converge_application_role_settings(conn)
        statements = [str(call.args[0]) for call in executed.call_args_list]
        assert statements
        assert not any("ALTER ROLE" in statement for statement in statements)
        assert capsys.readouterr().err == ""
    finally:
        pg_testdb.drop_test_database(database, pooled=False)


def test_concurrent_boots_converge_the_role_default_without_refusing(
    cluster_role_authority,
) -> None:
    """Concurrent ALTER ROLE on one catalog row must not fail a boot.

    ``ALTER ROLE ... IN DATABASE ... SET`` updates a shared
    ``pg_db_role_setting`` row, and simultaneous boots raise ``tuple
    concurrently updated`` there. That is the observed outage: every read of a
    local universe refused while two processes converged at once.
    """
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)

        def converge(_: int) -> None:
            with psycopg.connect(dsn) as conn:
                converge_application_role_settings(conn)
                conn.commit()

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            for outcome in pool.map(converge, range(12)):
                assert outcome is None

        with psycopg.connect(dsn) as conn:
            configured = conn.execute(
                "SELECT current_setting('idle_in_transaction_session_timeout')"
            ).fetchone()[0]
        assert configured == IDLE_IN_TRANSACTION_SESSION_TIMEOUT
    finally:
        pg_testdb.drop_test_database(database, pooled=False)


def test_unpersistable_role_default_degrades_and_leaves_the_session_usable(
    capsys,
    cluster_role_authority,
) -> None:
    """A role that cannot record its default still boots, guarded and diagnosed."""
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        denied = psycopg.errors.InsufficientPrivilege("permission denied to alter role")
        with psycopg.connect(dsn) as conn:
            with patch.object(
                conn,
                "execute",
                side_effect=_deny_statements_containing(conn, "ALTER ROLE", denied),
            ):
                converge_application_role_settings(conn)
            configured = conn.execute(
                "SELECT current_setting('idle_in_transaction_session_timeout')"
            ).fetchone()[0]
            assert configured == IDLE_IN_TRANSACTION_SESSION_TIMEOUT
            # The rollback in the degradation path leaves the connection able
            # to carry the rest of the convergence.
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        captured = capsys.readouterr()
        assert APPLICATION_ROLE_DEFAULT_NOT_PERSISTED in captured.err
        assert "Recover:" in captured.err
    finally:
        pg_testdb.drop_test_database(database, pooled=False)
