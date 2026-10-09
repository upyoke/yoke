"""Actual PostgreSQL CONNECT-fence role and restoration custody."""

import uuid

import psycopg
import pytest

from yoke_core.domain import source_authority_connect_fence as fence


def test_real_postgres_fence_blocks_ordinary_role_then_restores(
    monkeypatch,
    cluster_role_authority,
):
    from psycopg import conninfo, sql
    from runtime.api.fixtures import pg_testdb

    suffix = uuid.uuid4().hex[:10]
    admin_role = f"yoke_cutover_admin_{suffix}"
    ordinary_role = f"yoke_cutover_app_{suffix}"
    password = f"cutover-{suffix}-password"
    database = pg_testdb.create_test_database()
    maintenance = conninfo.make_conninfo(
        pg_testdb.dsn_for_test_database(database),
        dbname="postgres",
    )
    with psycopg.connect(maintenance, autocommit=True) as root:
        provider_role = str(root.execute("SELECT current_user").fetchone()[0])
        root.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(admin_role),
                sql.Literal(password),
            )
        )
        root.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(ordinary_role),
                sql.Literal(password),
            )
        )
        root.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(database),
                sql.Identifier(admin_role),
            )
        )
        root.execute(
            sql.SQL("GRANT pg_signal_backend TO {}").format(
                sql.Identifier(admin_role),
            )
        )
        root.execute(
            sql.SQL("GRANT pg_read_all_stats TO {}").format(
                sql.Identifier(admin_role),
            )
        )
    base = conninfo.conninfo_to_dict(pg_testdb.dsn_for_test_database(database))
    admin_dsn = conninfo.make_conninfo(
        **{**base, "user": admin_role, "password": password},
    )
    ordinary_dsn = conninfo.make_conninfo(
        **{**base, "user": ordinary_role, "password": password},
    )
    monkeypatch.setattr(
        fence,
        "PROVIDER_SUPERUSER_BYPASS_ROLES",
        frozenset({provider_role}),
    )
    ordinary = None
    admin_peer = None
    try:
        with psycopg.connect(admin_dsn) as admin:
            admin.execute(
                f'GRANT CONNECT ON DATABASE "{database}" TO "{ordinary_role}"'
            )
        ordinary = psycopg.connect(ordinary_dsn)
        assert ordinary.execute("SELECT current_user").fetchone() == (ordinary_role,)
        admin_peer = psycopg.connect(admin_dsn)
        assert admin_peer.execute("SELECT current_user").fetchone() == (admin_role,)
        with psycopg.connect(admin_dsn) as admin:
            assert sorted(
                entry["role"]
                for entry in fence.unauthorized_sessions(
                    admin,
                    admin_role=admin_role,
                )
            ) == sorted([admin_role, ordinary_role])
            staged = fence.install_connect_fence(
                admin,
                frozen_at="2026-07-14T00:00:00Z",
                service_stop_receipt="service-stopped",
            )
            assert staged["staged"] is True
            admin.commit()
            proved = fence.drain_and_prove_connect_fence(admin)
            assert proved["active"] is True
            assert proved["terminated_other_sessions"] == 2
        with pytest.raises(psycopg.OperationalError, match="CONNECT|permission"):
            psycopg.connect(ordinary_dsn)
        with pytest.raises(psycopg.Error):
            ordinary.execute("SELECT 1")
        with pytest.raises(psycopg.Error):
            admin_peer.execute("SELECT 1")
        ordinary.close()
        ordinary = None
        admin_peer.close()
        admin_peer = None
        with psycopg.connect(admin_dsn) as admin:
            restored = fence.restore_connect_fence(admin)
            admin.commit()
            assert restored["effective_connect_policy_restored"] is True
        with psycopg.connect(ordinary_dsn) as reconnected:
            assert reconnected.execute("SELECT 1").fetchone() == (1,)
    finally:
        if ordinary is not None:
            ordinary.close()
        if admin_peer is not None:
            admin_peer.close()
        pg_testdb.drop_test_database(database)
        with psycopg.connect(maintenance, autocommit=True) as root:
            root.execute(f'DROP ROLE IF EXISTS "{ordinary_role}"')
            root.execute(f'DROP ROLE IF EXISTS "{admin_role}"')
