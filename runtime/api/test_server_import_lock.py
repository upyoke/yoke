"""Server-lifetime and import-exclusivity lock coverage."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.api import server_entrypoint
from yoke_core.domain import db_backend, universe_startup_lock


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


def test_server_holds_shared_lock_through_serving_lifetime(monkeypatch):
    order: list[str] = []

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
    assert order == [
        "lock-enter",
        "schema",
        "permissions",
        "serve",
        "lock-exit",
    ]
