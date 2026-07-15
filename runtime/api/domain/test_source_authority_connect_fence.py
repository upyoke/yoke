"""Durable CONNECT-fence policy, membership, and restoration tests."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from yoke_core.domain import source_authority_connect_fence as fence


def _prod_access() -> list[dict[str, object]]:
    return [
        {
            "role": "rdsadmin", "superuser": True,
            "effective_connect": True, "inherits_admin": True,
        },
        {
            "role": "yoke_admin", "superuser": False,
            "effective_connect": True, "inherits_admin": True,
        },
        *[
            {
                "role": role, "superuser": False,
                "effective_connect": False, "inherits_admin": False,
            }
            for role in (
                "rdswriteforwarduser", "yoke_ci_deploy", "yoke_import_factory",
                "yoke_platform_app", "yoke_provisioner", "yoke_tenant_owner",
            )
        ],
    ]


def _saved_policy(*, datacl_was_null: bool = False) -> dict[str, object]:
    return {
        "schema": fence.FENCE_POLICY_SCHEMA,
        "database": "yoke_prod", "database_oid": 42,
        "owner_role": "yoke_admin", "admin_role": "yoke_admin",
        "datacl_was_null": datacl_was_null,
        "datacl_text": None if datacl_was_null else (
            "{=Tc/yoke_admin,yoke_admin=CTc/yoke_admin,"
            "yoke_ci_deploy=c/yoke_admin}"
        ),
        "connect_entries": [
            {
                "grantee": "PUBLIC", "grantor": "yoke_admin",
                "is_grantable": False,
            },
            {
                "grantee": "yoke_admin", "grantor": "yoke_admin",
                "is_grantable": True,
            },
            {
                "grantee": "yoke_ci_deploy", "grantor": "yoke_admin",
                "is_grantable": False,
            },
        ],
    }


def test_prod_role_shape_attests_only_provider_superuser_bypass():
    fence._validate_privileged_role_shape(_prod_access(), admin_role="yoke_admin")

    unexpected_super = _prod_access() + [{
        "role": "other_root", "superuser": True,
        "effective_connect": True, "inherits_admin": True,
    }]
    with pytest.raises(fence.SourceConnectFenceError, match="other_root"):
        fence._validate_privileged_role_shape(
            unexpected_super, admin_role="yoke_admin",
        )

    inherited = _prod_access()
    inherited[-1] = {**inherited[-1], "inherits_admin": True}
    with pytest.raises(fence.SourceConnectFenceError, match="yoke_tenant_owner"):
        fence._validate_privileged_role_shape(inherited, admin_role="yoke_admin")


def test_restore_replays_grantor_safe_policy_and_null_sentinel(monkeypatch):
    original = _saved_policy(datacl_was_null=True)
    current = {**original, "datacl_was_null": False, "connect_entries": []}
    restored = {**current, "connect_entries": original["connect_entries"]}
    policies = iter([current, restored])
    grants = []
    monkeypatch.setattr(
        fence, "fence_state", lambda *_args: {
            "policy": original, "frozen_at": "now",
            "service_stop_receipt": "stopped",
        },
    )
    monkeypatch.setattr(fence, "connect_policy", lambda _conn: next(policies))
    monkeypatch.setattr(fence, "_clear_connect_grants", lambda *_args: None)
    monkeypatch.setattr(
        fence, "_grant_connect", lambda _conn, **kwargs: grants.append(kwargs),
    )
    dropped = []
    monkeypatch.setattr(fence, "_drop_fence_state", lambda _conn: dropped.append(True))

    report = fence.restore_connect_fence(object())

    assert report["original_datacl_was_null"] is True
    assert report["effective_connect_policy_restored"] is True
    assert grants == [
        {"database": "yoke_prod", "grantee": "PUBLIC", "grantable": False},
        {"database": "yoke_prod", "grantee": "yoke_admin", "grantable": True},
        {
            "database": "yoke_prod", "grantee": "yoke_ci_deploy",
            "grantable": False,
        },
    ]
    assert dropped == [True]


def test_drain_occurs_only_against_committed_fence_and_names_provider_bypass(
    monkeypatch,
):
    original = _saved_policy()
    monkeypatch.setattr(
        fence, "fence_state", lambda *_args: {
            "policy": original, "frozen_at": "now",
            "service_stop_receipt": "stopped",
        },
    )
    monkeypatch.setattr(
        fence, "login_role_access", lambda *_args, **_kwargs: _prod_access(),
    )
    monkeypatch.setattr(
        fence, "admin_memberships",
        lambda _conn: ["pg_read_all_stats", "pg_signal_backend", "yoke_admin"],
    )
    monkeypatch.setattr(
        fence, "terminate_unauthorized_sessions", lambda *_args, **_kwargs: 4,
    )
    monkeypatch.setattr(
        fence, "unauthorized_sessions", lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        fence, "connect_fence_status", lambda _conn: {
            "active": True,
            "provider_superuser_bypass_roles": ["rdsadmin"],
        },
    )

    report = fence.drain_and_prove_connect_fence(object())

    assert report["active"] is True
    assert report["terminated_other_sessions"] == 4
    assert report["provider_superuser_bypass_roles"] == ["rdsadmin"]


def test_live_provider_superuser_session_requires_attended_drain(monkeypatch):
    original = _saved_policy()
    monkeypatch.setattr(
        fence, "fence_state", lambda *_args: {
            "policy": original, "frozen_at": "now",
            "service_stop_receipt": "stopped",
        },
    )
    monkeypatch.setattr(
        fence, "login_role_access", lambda *_args, **_kwargs: _prod_access(),
    )
    monkeypatch.setattr(
        fence, "admin_memberships",
        lambda _conn: ["pg_read_all_stats", "pg_signal_backend", "yoke_admin"],
    )
    monkeypatch.setattr(
        fence, "terminate_unauthorized_sessions", lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        fence, "_wait_for_session_drain", lambda *_args, **_kwargs: [{
            "pid": 42, "role": "rdsadmin", "superuser": True,
        }],
    )

    with pytest.raises(
        fence.SourceConnectFenceError,
        match="provider-superuser sessions require attended external drain: rdsadmin",
    ):
        fence.drain_and_prove_connect_fence(object())


def test_restore_refuses_unreplayable_grantor(monkeypatch):
    original = _saved_policy()
    original["connect_entries"][0]["grantor"] = "legacy_admin"
    monkeypatch.setattr(fence, "fence_state", lambda *_args: None)
    monkeypatch.setattr(fence, "connect_policy", lambda _conn: original)

    # The preflight belongs to install and rejects before any ACL mutation.
    with pytest.raises(fence.SourceConnectFenceError, match="grantors"):
        fence.install_connect_fence(
            object(), frozen_at="now", service_stop_receipt="stopped",
        )


def test_real_postgres_fence_blocks_ordinary_role_then_restores(
    monkeypatch, cluster_role_authority,
):
    from psycopg import conninfo, sql
    from runtime.api.fixtures import pg_testdb

    suffix = uuid.uuid4().hex[:10]
    admin_role = f"yoke_cutover_admin_{suffix}"
    ordinary_role = f"yoke_cutover_app_{suffix}"
    password = f"cutover-{suffix}-password"
    database = pg_testdb.create_test_database()
    maintenance = conninfo.make_conninfo(
        pg_testdb.dsn_for_test_database(database), dbname="postgres",
    )
    with psycopg.connect(maintenance, autocommit=True) as root:
        provider_role = str(root.execute("SELECT current_user").fetchone()[0])
        root.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(admin_role), sql.Literal(password),
        ))
        root.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(ordinary_role), sql.Literal(password),
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
    ordinary_dsn = conninfo.make_conninfo(
        **{**base, "user": ordinary_role, "password": password},
    )
    monkeypatch.setattr(
        fence, "PROVIDER_SUPERUSER_BYPASS_ROLES", frozenset({provider_role}),
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
                    admin, admin_role=admin_role,
                )
            ) == sorted([admin_role, ordinary_role])
            staged = fence.install_connect_fence(
                admin, frozen_at="2026-07-14T00:00:00Z",
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
