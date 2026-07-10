"""Tests for the container-facing uvicorn entrypoint."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.api import server_entrypoint
from yoke_core.domain.actor_permissions import (
    PERM_DB_READ_RAW,
    seed_roles_and_permissions,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_TABLE


def test_resolve_settings_reads_env_defaults() -> None:
    settings = server_entrypoint.resolve_settings(
        argv=[], env={"YOKE_API_PORT": "9000", "YOKE_API_LOG_LEVEL": "warning"},
    )
    assert settings.port == 9000
    assert settings.log_level == "warning"
    assert settings.app == server_entrypoint.DEFAULT_APP


def test_main_disables_uvicorn_access_log_and_dictconfig(monkeypatch) -> None:
    """13143: keep CloudWatch on one JSON stream.

    uvicorn must be launched with access_log=False (the bearer-token
    middleware emits a structured HttpRequestCompleted per request) and
    log_config=None (uvicorn must not install its plain-text dictConfig
    over the app's JSON root handler).
    """
    captured: dict[str, object] = {}

    fake_uvicorn = types.ModuleType("uvicorn")

    def _run(app, **kwargs):  # noqa: ANN001
        captured["app"] = app
        captured.update(kwargs)

    fake_uvicorn.run = _run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    # Keep this test focused on uvicorn config; the catalog reseed has its own.
    monkeypatch.setattr(server_entrypoint, "universe_is_born", lambda: True)
    monkeypatch.setattr(server_entrypoint, "admin_credential_exists", lambda: True)
    monkeypatch.setattr(server_entrypoint, "ensure_core_schema", lambda: None)
    monkeypatch.setattr(server_entrypoint, "ensure_permission_catalog", lambda: None)

    rc = server_entrypoint.main(argv=[])

    assert rc == 0
    assert captured["access_log"] is False
    assert captured["log_config"] is None


def _disposable_db_conn():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    return pg_testdb.drop_database_on_close(conn, name)


def _has_permission(conn, key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM permissions WHERE key = %s", (key,)
    ).fetchone()
    return row is not None


def test_ensure_permission_catalog_heals_dropped_permission(monkeypatch) -> None:
    """A boot reseed restores a code-defined permission missing from the DB.

    This is the deploy-drift fix: new permissions in the deployed code reach a
    long-lived DB on the next boot without a manual seed.
    """
    conn = _disposable_db_conn()
    create_core_tables(conn)
    seed_project_identities(conn)
    # api_tokens carries an enforced FK to actors; create identity tables first.
    create_actor_identity_tables(conn)
    create_auth_tables(conn)
    seed_roles_and_permissions(conn)
    # Simulate catalog drift: the DB predates this permission.
    conn.execute("DELETE FROM role_permissions")
    conn.execute("DELETE FROM permissions WHERE key = %s", (PERM_DB_READ_RAW,))
    conn.commit()
    assert _has_permission(conn, PERM_DB_READ_RAW) is False

    @contextmanager
    def _fake_connect(*_args, **_kwargs):
        yield conn

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", _fake_connect)
    server_entrypoint.ensure_permission_catalog()

    assert _has_permission(conn, PERM_DB_READ_RAW) is True


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT to_regclass(%s)",
        (table,),
    ).fetchone()
    return row[0] is not None


def test_ensure_core_schema_heals_missing_core_table(monkeypatch) -> None:
    """Container boot applies idempotent schema init before serving."""
    conn = _disposable_db_conn()
    create_core_tables(conn)
    conn.execute(f"DROP TABLE {STRATEGY_DOCS_TABLE}")
    conn.commit()
    assert _table_exists(conn, STRATEGY_DOCS_TABLE) is False

    @contextmanager
    def _fake_connect(*_args, **_kwargs):
        yield conn

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", _fake_connect)

    server_entrypoint.ensure_core_schema()

    assert _table_exists(conn, STRATEGY_DOCS_TABLE) is True


def test_main_ensures_schema_and_reseeds_catalog_before_serving(monkeypatch) -> None:
    """Born-universe boot keeps the idempotent ensure + reseed contract."""
    order: list[str] = []
    monkeypatch.setattr(server_entrypoint, "universe_is_born", lambda: True)
    monkeypatch.setattr(server_entrypoint, "admin_credential_exists", lambda: True)
    monkeypatch.setattr(
        server_entrypoint, "ensure_core_schema",
        lambda: order.append("schema"),
    )
    monkeypatch.setattr(
        server_entrypoint, "ensure_permission_catalog",
        lambda: order.append("seed"),
    )
    monkeypatch.setattr(
        server_entrypoint, "birth_universe",
        lambda: order.append("birth"),
    )
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **k: order.append("serve")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    rc = server_entrypoint.main(argv=[])

    assert rc == 0
    assert order == ["schema", "seed", "serve"]


def test_main_births_universe_before_serving_when_empty(monkeypatch) -> None:
    """Empty-DB boot takes the full-birth path, never the partial ensures."""
    order: list[str] = []
    monkeypatch.setattr(server_entrypoint, "universe_is_born", lambda: False)
    monkeypatch.setattr(
        server_entrypoint, "ensure_core_schema",
        lambda: order.append("schema"),
    )
    monkeypatch.setattr(
        server_entrypoint, "ensure_permission_catalog",
        lambda: order.append("seed"),
    )
    monkeypatch.setattr(
        server_entrypoint, "birth_universe",
        lambda: order.append("birth"),
    )
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **k: order.append("serve")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    rc = server_entrypoint.main(argv=[])

    assert rc == 0
    assert order == ["birth", "serve"]


def test_main_completes_interrupted_birth_when_born_but_credential_less(
    monkeypatch,
) -> None:
    """Born with no minted credential re-enters birth, never the born path."""
    order: list[str] = []
    monkeypatch.setattr(server_entrypoint, "universe_is_born", lambda: True)
    monkeypatch.setattr(
        server_entrypoint, "admin_credential_exists", lambda: False,
    )
    monkeypatch.setattr(
        server_entrypoint, "ensure_core_schema",
        lambda: order.append("schema"),
    )
    monkeypatch.setattr(
        server_entrypoint, "ensure_permission_catalog",
        lambda: order.append("seed"),
    )
    monkeypatch.setattr(
        server_entrypoint, "birth_universe",
        lambda: order.append("birth"),
    )
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **k: order.append("serve")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    rc = server_entrypoint.main(argv=[])

    assert rc == 0
    assert order == ["birth", "serve"]


def test_empty_db_birth_failure_aborts_before_serving(monkeypatch) -> None:
    """A failed birth must propagate — no uvicorn over a half-born universe."""
    monkeypatch.setattr(server_entrypoint, "universe_is_born", lambda: False)

    def _boom() -> None:
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(server_entrypoint, "birth_universe", _boom)
    fake_uvicorn = types.ModuleType("uvicorn")
    served: list[bool] = []
    fake_uvicorn.run = lambda *a, **k: served.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        server_entrypoint.main(argv=[])
    assert served == []


def test_ensure_permission_catalog_is_fail_soft(monkeypatch) -> None:
    """A reseed failure must not raise (it must never block serving)."""
    @contextmanager
    def _boom(*_args, **_kwargs):
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", _boom)
    # Must not raise.
    server_entrypoint.ensure_permission_catalog()


def test_first_boot_on_empty_db_births_universe_and_prints_token_once(
    monkeypatch, capsys,
) -> None:
    """End-to-end first boot against a REAL empty database.

    The boot births the universe (org card named from the env var, one
    admin human actor with the org admin role, one active token whose raw
    value is printed exactly once), and a reboot of the now-born universe
    neither re-mints nor re-prints.
    """
    from yoke_core.domain.api_tokens import (
        DEFAULT_ADMIN_ACTOR_LABEL,
        INITIAL_ADMIN_TOKEN_NAME,
        TOKEN_PREFIX,
        verify_token,
    )

    name = pg_testdb.create_test_database()  # empty: no schema, no rows
    monkeypatch.setenv("YOKE_PG_DSN", pg_testdb.dsn_for_test_database(name))
    monkeypatch.setenv(server_entrypoint.ORG_NAME_ENV, "Probe Fleet")
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **k: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    try:
        rc = server_entrypoint.main(argv=[])
        assert rc == 0
        out = capsys.readouterr().out
        assert out.count(server_entrypoint.FIRST_BOOT_TOKEN_MARKER) == 1
        assert "yoke connect" in out
        raw_token = next(
            line.strip()
            for line in out.splitlines()
            if line.strip().startswith(TOKEN_PREFIX)
        )

        conn = pg_testdb.connect_test_database(name)
        try:
            orgs = conn.execute(
                "SELECT slug, name FROM organizations"
            ).fetchall()
            assert [(r[0], r[1]) for r in orgs] == [("default", "Probe Fleet")]

            verified = verify_token(conn, raw_token)
            assert verified.name == INITIAL_ADMIN_TOKEN_NAME

            # The canonical human actor the init chain seeds IS the admin
            # actor: one human row, labeled with the neutral admin label.
            humans = conn.execute(
                "SELECT COUNT(*) FROM actors WHERE kind = 'human'"
            ).fetchone()
            assert int(humans[0]) == 1
            label_rows = conn.execute(
                "SELECT label FROM actor_labels WHERE actor_id = %s",
                (verified.actor_id,),
            ).fetchall()
            assert {str(r[0]) for r in label_rows} == {DEFAULT_ADMIN_ACTOR_LABEL}

            org_admin = conn.execute(
                "SELECT 1 FROM actor_org_roles aor "
                "JOIN roles r ON r.id = aor.role_id "
                "WHERE aor.actor_id = %s AND r.name = 'admin'",
                (verified.actor_id,),
            ).fetchone()
            assert org_admin is not None
        finally:
            conn.close()

        # Reboot of the born universe: current idempotent behavior, no
        # re-mint, no re-print.
        rc = server_entrypoint.main(argv=[])
        assert rc == 0
        out = capsys.readouterr().out
        assert server_entrypoint.FIRST_BOOT_TOKEN_MARKER not in out
        assert TOKEN_PREFIX not in out
        conn = pg_testdb.connect_test_database(name)
        try:
            tokens = conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()
            assert int(tokens[0]) == 1
        finally:
            conn.close()
    finally:
        pg_testdb.drop_test_database(name)


def test_interrupted_birth_completes_on_next_boot(monkeypatch, capsys) -> None:
    """A birth that dies after the born-ness commit resumes on the next boot.

    The org identity card (the born-ness sentinel) commits early in the
    init chain while the admin token mints at the very end of the birth. A
    boot killed in between must not convert into a served, permanently
    credential-less universe: the next boot detects the born-but-tokenless
    shape, re-enters the idempotent birth, and mints + prints the one-time
    admin token before serving.
    """
    from yoke_core.domain import environment_bootstrap
    from yoke_core.domain.api_tokens import (
        INITIAL_ADMIN_TOKEN_NAME,
        TOKEN_PREFIX,
        verify_token,
    )

    name = pg_testdb.create_test_database()  # empty: no schema, no rows
    monkeypatch.setenv("YOKE_PG_DSN", pg_testdb.dsn_for_test_database(name))
    fake_uvicorn = types.ModuleType("uvicorn")
    served: list[bool] = []
    fake_uvicorn.run = lambda *a, **k: served.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    real_populate = environment_bootstrap.populate_event_registry
    fail = {"on": True}

    def _flaky_populate(*args, **kwargs):  # noqa: ANN001
        if fail["on"]:
            raise RuntimeError("birth interrupted")
        return real_populate(*args, **kwargs)

    monkeypatch.setattr(
        environment_bootstrap, "populate_event_registry", _flaky_populate,
    )
    try:
        with pytest.raises(RuntimeError, match="birth interrupted"):
            server_entrypoint.main(argv=[])
        assert served == []
        assert server_entrypoint.FIRST_BOOT_TOKEN_MARKER not in capsys.readouterr().out

        # The failed boot left the half-born shape: the born-ness sentinel
        # committed, the credential never minted.
        conn = pg_testdb.connect_test_database(name)
        try:
            orgs = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()
            assert int(orgs[0]) == 1
            tokens = conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()
            assert int(tokens[0]) == 0
        finally:
            conn.close()

        fail["on"] = False
        rc = server_entrypoint.main(argv=[])
        assert rc == 0
        assert served == [True]
        out = capsys.readouterr().out
        assert out.count(server_entrypoint.FIRST_BOOT_TOKEN_MARKER) == 1
        raw_token = next(
            line.strip()
            for line in out.splitlines()
            if line.strip().startswith(TOKEN_PREFIX)
        )
        conn = pg_testdb.connect_test_database(name)
        try:
            verified = verify_token(conn, raw_token)
            assert verified.name == INITIAL_ADMIN_TOKEN_NAME
        finally:
            conn.close()

        # A completed universe boots the idempotent born path: no re-mint,
        # no re-print.
        rc = server_entrypoint.main(argv=[])
        assert rc == 0
        out = capsys.readouterr().out
        assert server_entrypoint.FIRST_BOOT_TOKEN_MARKER not in out
        conn = pg_testdb.connect_test_database(name)
        try:
            tokens = conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()
            assert int(tokens[0]) == 1
        finally:
            conn.close()
    finally:
        pg_testdb.drop_test_database(name)
