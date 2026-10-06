"""Persistent counters serialize concurrent workers and expire by time window."""

from concurrent.futures import ThreadPoolExecutor

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_helpers
from yoke_core.domain import machine_authorization_limits as limits
from yoke_core.domain import machine_authorization_codes as codes


def test_shared_workers_cannot_exceed_start_budget():
    with pg_testdb.test_database() as conn:

        def admit(_):
            with db_helpers.connect() as worker:
                return limits.admit_client(
                    worker, client="192.0.2.1", operation="start", now=61
                )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(admit, range(limits.START_REQUESTS + 4)))
        assert sum(delay == 0 for _, delay in results) == limits.START_REQUESTS
        assert {delay for _, delay in results} == {0, 59}
        key = results[0][0]
        assert key != "192.0.2.1"
        assert (
            conn.execute(
                "SELECT request_count FROM machine_authorization_rate_limits WHERE client_key=%s AND operation='start'",
                (key,),
            ).fetchone()[0]
            == limits.START_REQUESTS + 4
        )
        # Reconnecting preserves the budget; clients/operations remain separate.
        with db_helpers.connect() as restarted:
            assert (
                limits.admit_client(
                    restarted, client="192.0.2.1", operation="start", now=62
                )[1]
                == 58
            )
            assert (
                limits.admit_client(
                    restarted, client="192.0.2.2", operation="start", now=62
                )[1]
                == 0
            )
            assert (
                limits.admit_client(
                    restarted, client="192.0.2.1", operation="poll", now=62
                )[1]
                == 0
            )
            assert (
                limits.admit_client(
                    restarted, client="192.0.2.1", operation="start", now=120
                )[1]
                == 0
            )
            limits.admit_client(
                restarted, client="192.0.2.3", operation="start", now=240
            )
            assert (
                restarted.execute(
                    "SELECT count(*) FROM machine_authorization_rate_limits WHERE window_start < 180"
                ).fetchone()[0]
                == 0
            )


def test_concurrent_starts_serialize_the_pending_client_cap():
    from uuid import uuid4

    with pg_testdb.test_database() as conn:

        def start(_):
            with db_helpers.connect() as worker:
                try:
                    return codes.start(
                        worker,
                        origin="https://team.example",
                        machine_id=str(uuid4()),
                        machine_name="laptop",
                        client_key="one-peer",
                    )
                except codes.MachineAuthorizationError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(start, range(limits.CLIENT_PENDING_CODES + 4)))
        assert (
            sum(isinstance(result, dict) for result in results)
            == limits.CLIENT_PENDING_CODES
        )
        assert results.count("authorization_client_capacity") == 4
        assert (
            conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[
                0
            ]
            == limits.CLIENT_PENDING_CODES
        )


def test_boot_restores_legacy_pending_client_column(tmp_path, monkeypatch):
    from runtime.api.domain import test_boot_schema_column_convergence as boot
    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
    from yoke_core.domain.schema_init import converge_core_schema

    with init_test_db(
        tmp_path, apply_schema=boot._apply_complete_control_plane_schema
    ) as db_path:
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "ALTER TABLE machine_authorization_codes DROP COLUMN client_key"
            )
            conn.commit()
            converge_core_schema(conn)
            converge_core_schema(conn)
            assert "client_key" in boot._column_map(conn)["machine_authorization_codes"]
            lookups = boot._record_boot_column_lookups(conn, monkeypatch)
            assert ("machine_authorization_codes", "client_key") in lookups
            assert {
                "client_key",
                "operation",
                "window_start",
                "request_count",
            } <= boot._column_map(conn)["machine_authorization_rate_limits"]

        finally:
            conn.close()
