"""PostgreSQL transaction guards for dispatch waits and application roles."""

from __future__ import annotations

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
    IDLE_IN_TRANSACTION_SESSION_TIMEOUT,
    converge_application_role_settings,
)
from yoke_core.domain.yoke_function_dispatch_idempotency import (
    request_reservation,
)
from runtime.api.fixtures import pg_testdb


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


def test_application_role_declares_bounded_idle_transaction_timeout() -> None:
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
