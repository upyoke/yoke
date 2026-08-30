"""Permanent contracts for re-proving shipped migration invariants."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.tools.yoke_migration_fleet import (
    converge,
    history_names,
    load_module,
    pending_names,
)
from yoke_core.domain import db_backend, environment_bootstrap
from yoke_core.domain.migration_fleet_applied_invariants import (
    applied_shipped_names,
    verify_applied_history_invariants,
)
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV


def test_pending_entry_can_retire_an_applied_predecessor() -> None:
    def removed_surface(_conn: Any) -> None:
        raise AssertionError("retired surface is absent")

    modules = {
        "0001_presence": SimpleNamespace(invariants=removed_surface),
        "0002_removal": SimpleNamespace(
            RETIRES_INVARIANTS=("0001_presence",)
        ),
    }

    detail = verify_applied_history_invariants(
        object(),
        ("0001_presence",),
        history=tuple(modules),
        load_module=modules.__getitem__,
    )

    assert detail is None


def test_empty_database_converges_full_history_and_live_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(database)
    monkeypatch.setenv(db_backend.PG_DSN_ENV, dsn)
    monkeypatch.setenv(RESTORE_POINT_ENV, "snapshot:full-history-invariants")
    # Exercise the existing-universe branch against an otherwise empty
    # database so boot convergence applies every entry instead of birth-
    # stamping the current schema.
    monkeypatch.setattr(
        environment_bootstrap, "universe_is_born_on", lambda _conn: True
    )
    conn = pg_testdb.connect_test_database(database)
    try:
        history = history_names()
        assert conn.execute("SELECT to_regclass('items')").fetchone()[0] is None
        assert pending_names(conn, history) == history

        converge(conn, dsn)

        applied = applied_shipped_names(history, pending_names, conn)
        applied_by = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT applied_by FROM applied_migrations"
            ).fetchall()
        }
        assert applied == history
        assert applied_by == {"boot-converge"}
        assert verify_applied_history_invariants(
            conn,
            applied,
            history=history,
            load_module=load_module,
            redact=dsn,
        ) is None
    finally:
        conn.close()
        pg_testdb.drop_test_database(database)
