"""Effective-role regression for source CONNECT-fence administration."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import conninfo, sql

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import source_authority_connect_fence as fence


def test_noinherit_membership_does_not_attest_effective_drain_privileges(
    monkeypatch, cluster_role_authority,
):
    suffix = uuid.uuid4().hex[:10]
    admin_role = f"yoke_noinherit_admin_{suffix}"
    password = f"cutover-{suffix}-password"
    database = pg_testdb.create_test_database()
    maintenance = conninfo.make_conninfo(
        pg_testdb.dsn_for_test_database(database), dbname="postgres",
    )
    with psycopg.connect(maintenance, autocommit=True) as root:
        provider_role = str(root.execute("SELECT current_user").fetchone()[0])
        root.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
            sql.Identifier(admin_role), sql.Literal(password),
        ))
        root.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
            sql.Identifier(database), sql.Identifier(admin_role),
        ))
        root.execute(sql.SQL("GRANT pg_signal_backend TO {}").format(
            sql.Identifier(admin_role),
        ))
        root.execute(sql.SQL("GRANT pg_read_all_stats TO {}").format(
            sql.Identifier(admin_role),
        ))
    base = conninfo.conninfo_to_dict(pg_testdb.dsn_for_test_database(database))
    admin_dsn = conninfo.make_conninfo(
        **{**base, "user": admin_role, "password": password},
    )
    monkeypatch.setattr(
        fence, "PROVIDER_SUPERUSER_BYPASS_ROLES", frozenset({provider_role}),
    )
    try:
        with psycopg.connect(admin_dsn) as admin:
            member, usage = admin.execute(
                "SELECT pg_has_role(current_user, 'pg_signal_backend', 'MEMBER'), "
                "pg_has_role(current_user, 'pg_signal_backend', 'USAGE')"
            ).fetchone()
            assert (member, usage) == (True, False)
            effective = fence.admin_memberships(admin)
            assert "pg_signal_backend" not in effective
            assert "pg_read_all_stats" not in effective
            with pytest.raises(
                fence.SourceConnectFenceError,
                match="lacks required fence memberships",
            ):
                fence.install_connect_fence(
                    admin, frozen_at="now", service_stop_receipt="stopped",
                )
    finally:
        pg_testdb.drop_test_database(database)
        with psycopg.connect(maintenance, autocommit=True) as root:
            root.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(
                sql.Identifier(admin_role),
            ))
