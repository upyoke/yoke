"""Server-lifetime and import-exclusivity lock coverage."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.api import server_entrypoint
from yoke_core.domain import db_backend, universe_startup_lock

_HOSTED = {
    "YOKE_PG_DSN_FILE": universe_startup_lock.HOSTED_TENANT_DSN_FILE,
    "YOKE_API_HOST": universe_startup_lock.HOSTED_TENANT_API_HOST,
    "YOKE_API_PORT": universe_startup_lock.HOSTED_TENANT_API_PORT,
    "YOKE_ENVIRONMENT": "stage",
}


def test_shared_server_lock_refuses_import_until_every_server_releases():
    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        with universe_startup_lock.server_startup_guard(dsn):
            with universe_startup_lock.server_startup_guard(dsn):
                with pytest.raises(universe_startup_lock.UniverseStartupBusy):
                    with universe_startup_lock.exclusive_import_guard(dsn):
                        raise AssertionError("exclusive lock must not be entered")
        with universe_startup_lock.exclusive_import_guard(dsn):
            pass
    finally:
        pg_testdb.drop_test_database(name)


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, False),
        ({**_HOSTED, "YOKE_SERVER_MODE": "self-host"}, True),
        ({**_HOSTED, "YOKE_ENVIRONMENT": "prod"}, True),
        ({**_HOSTED, "YOKE_ENVIRONMENT": "ephemeral-acme"}, True),
        ({**_HOSTED, "YOKE_API_PORT": "8765"}, False),
        (
            {
                "YOKE_PG_DSN_FILE": "/run/secrets/yoke-db-dsn",
                "YOKE_API_HOST": "0.0.0.0",
                "YOKE_API_PORT": "8765",
                "YOKE_SERVER_MODE": "self-host",
            },
            False,
        ),
        ({"YOKE_API_HOST": "127.0.0.1", "YOKE_API_PORT": "8765"}, False),
        ({**_HOSTED, "YOKE_PG_DSN_FILE": "/var/lib/yoke/dsn"}, False),
    ],
)
def test_hosted_tenant_container_process_conjunction(env, expected):
    assert universe_startup_lock.hosted_tenant_container_process(env) is expected


def _clear_hosted_env(monkeypatch) -> None:
    for key in (
        "YOKE_PG_DSN_FILE",
        "YOKE_API_HOST",
        "YOKE_API_PORT",
        "YOKE_ENVIRONMENT",
        "YOKE_SERVER_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


def _run_main(monkeypatch, *, env: dict[str, str] | None = None) -> list[str]:
    order: list[str] = []
    _clear_hosted_env(monkeypatch)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)

    @contextmanager
    def guard(dsn):
        assert dsn == "postgresql://startup-lock-test"
        order.append("lock-enter")
        try:
            yield
        finally:
            order.append("lock-exit")

    monkeypatch.setattr(
        db_backend, "resolve_pg_dsn", lambda: "postgresql://startup-lock-test"
    )
    monkeypatch.setattr(universe_startup_lock, "server_startup_guard", guard)
    monkeypatch.setattr(server_entrypoint, "universe_is_born", lambda: True)
    monkeypatch.setattr(server_entrypoint, "admin_credential_exists", lambda: True)
    monkeypatch.setattr(
        server_entrypoint, "ensure_core_schema", lambda: order.append("schema")
    )
    monkeypatch.setattr(
        server_entrypoint,
        "ensure_permission_catalog",
        lambda: order.append("permissions"),
    )
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **k: order.append("serve")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    assert server_entrypoint.main(argv=[]) == 0
    return order


def test_server_holds_shared_lock_through_serving_lifetime(monkeypatch):
    assert _run_main(monkeypatch) == [
        "lock-enter",
        "schema",
        "permissions",
        "serve",
        "lock-exit",
    ]


def test_local_runtime_retains_guard_through_serve(monkeypatch):
    assert _run_main(
        monkeypatch,
        env={"YOKE_API_HOST": "127.0.0.1", "YOKE_API_PORT": "8765"},
    )[-2:] == ["serve", "lock-exit"]


def test_self_host_retains_guard_through_serve(monkeypatch):
    assert _run_main(
        monkeypatch,
        env={
            "YOKE_PG_DSN_FILE": "/run/secrets/yoke-db-dsn",
            "YOKE_API_HOST": "0.0.0.0",
            "YOKE_API_PORT": "8765",
            "YOKE_SERVER_MODE": "self-host",
        },
    )[-2:] == ["serve", "lock-exit"]


def test_preview_ephemeral_retains_guard_through_serve(monkeypatch):
    assert _run_main(
        monkeypatch,
        env={
            **_HOSTED,
            "YOKE_ENVIRONMENT": "ephemeral-acme",
            "YOKE_API_PORT": "8765",
        },
    )[-2:] == ["serve", "lock-exit"]


def test_hosted_releases_guard_before_serve(monkeypatch):
    assert _run_main(monkeypatch, env=_HOSTED) == [
        "lock-enter",
        "schema",
        "permissions",
        "lock-exit",
        "serve",
    ]


def test_startup_failure_releases_guard_without_serving(monkeypatch):
    _clear_hosted_env(monkeypatch)
    for key, value in _HOSTED.items():
        monkeypatch.setenv(key, value)
    order: list[str] = []

    @contextmanager
    def guard(dsn):
        order.append("lock-enter")
        try:
            yield
        finally:
            order.append("lock-exit")

    monkeypatch.setattr(
        db_backend, "resolve_pg_dsn", lambda: "postgresql://startup-lock-test"
    )
    monkeypatch.setattr(universe_startup_lock, "server_startup_guard", guard)
    monkeypatch.setattr(server_entrypoint, "universe_is_born", lambda: True)
    monkeypatch.setattr(server_entrypoint, "admin_credential_exists", lambda: True)

    def _boom() -> None:
        order.append("schema")
        raise RuntimeError("schema-failed")

    monkeypatch.setattr(server_entrypoint, "ensure_core_schema", _boom)
    monkeypatch.setattr(
        server_entrypoint,
        "ensure_permission_catalog",
        lambda: order.append("permissions"),
    )
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **k: order.append("serve")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    with pytest.raises(RuntimeError, match="schema-failed"):
        server_entrypoint.main(argv=[])
    assert order == ["lock-enter", "schema", "lock-exit"]


def test_pause_preserves_readonly_server_import_exclusion(monkeypatch, tmp_path):
    import psycopg
    from yoke_core.domain import universe_source_pause

    monkeypatch.setenv("YOKE_SERVER_MODE", "self-host")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    with pg_testdb.test_database():
        dsn = db_backend.resolve_pg_dsn()
        with universe_startup_lock.server_startup_guard(dsn):
            universe_source_pause.pause(dsn)
            try:
                with universe_source_pause.pause_owner():
                    with pytest.raises(universe_startup_lock.UniverseStartupBusy):
                        with universe_startup_lock.exclusive_import_guard(dsn):
                            pass
                # Another server worker can recover its read-only coordination
                # session while normal application acquisition stays refused.
                with universe_startup_lock.server_startup_guard(dsn):
                    with pytest.raises(universe_source_pause.UniversePausedError):
                        db_backend.connect_psycopg(dsn)
                    with universe_startup_lock._server_connection(dsn) as coordination:
                        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                            coordination.execute(
                                "CREATE TABLE forbidden_write(id integer)"
                            )
            finally:
                universe_source_pause.resume(dsn)
            with pytest.raises(universe_startup_lock.UniverseStartupBusy):
                with universe_startup_lock.exclusive_import_guard(dsn):
                    pass
        with universe_startup_lock.exclusive_import_guard(dsn):
            pass


def test_paused_restart_defers_schema_but_serves_resume(monkeypatch, tmp_path):
    from yoke_core.domain import universe_source_pause

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    dsn = "postgresql://startup-lock-test"
    marker = universe_source_pause._marker(dsn)
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    order = _run_main(monkeypatch, env={"YOKE_SERVER_MODE": "self-host"})
    assert order == ["lock-enter", "serve", "lock-exit"]
    assert marker.exists()
    with pytest.raises(universe_source_pause.UniversePausedError):
        universe_source_pause.require_running(dsn)


def test_paused_worker_validation_closes_its_readonly_session(monkeypatch, tmp_path):
    from yoke_core.api import main
    from yoke_core.domain import universe_source_pause

    monkeypatch.setenv("YOKE_SERVER_MODE", "self-host")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    observed = []
    original = main.invalid_item_workflow_stages

    def inspect(conn):
        observed.append(conn.execute("SHOW transaction_read_only").fetchone()[0])
        return original(conn)

    monkeypatch.setattr(main, "invalid_item_workflow_stages", inspect)
    with pg_testdb.test_database() as source:
        source.commit()
        dsn = db_backend.resolve_pg_dsn()
        universe_source_pause.pause(dsn)
        try:
            with (
                universe_source_pause.startup_access(dsn),
                db_backend.bound_pg_dsn(dsn),
            ):
                main._ensure_db_initialized()
            assert observed == ["on"]
            with (
                universe_source_pause.pause_owner(),
                db_backend.connect_psycopg(dsn) as probe,
            ):
                assert universe_startup_lock.application_sessions(probe) == []
            with pytest.raises(universe_source_pause.UniversePausedError):
                db_backend.connect_psycopg(dsn)
        finally:
            universe_source_pause.resume(dsn)
