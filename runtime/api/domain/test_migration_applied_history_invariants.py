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
    RETIRED_STANDING_INVARIANTS,
    applied_shipped_names,
    verify_applied_history_invariants,
)
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV


def test_pending_entry_can_retire_an_applied_predecessor() -> None:
    def removed_surface(_conn: Any) -> None:
        raise AssertionError("retired surface is absent")

    modules = {
        "0001_presence": SimpleNamespace(invariants=removed_surface),
        "0002_removal": SimpleNamespace(RETIRES_INVARIANTS=("0001_presence",)),
    }

    detail = verify_applied_history_invariants(
        object(),
        ("0001_presence",),
        history=tuple(modules),
        load_module=modules.__getitem__,
    )

    assert detail is None


def test_retired_standing_invariant_names_its_skip_and_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    name, reason = next(iter(RETIRED_STANDING_INVARIANTS.items()))

    def wrong_standing_invariant(_conn: Any) -> None:
        raise AssertionError("this invariant must be skipped")

    detail = verify_applied_history_invariants(
        object(),
        (name,),
        history=(name,),
        load_module=lambda _name: SimpleNamespace(
            invariants=wrong_standing_invariant
        ),
    )

    assert detail is None
    assert capsys.readouterr().out == (
        f"converging {name}: standing invariant skipped -- {reason}\n"
    )


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
        assert (
            verify_applied_history_invariants(
                conn,
                applied,
                history=history,
                load_module=load_module,
                redact=dsn,
            )
            is None
        )

        # A session whose provider attested a model but whose ask was never
        # recorded is the normal shape of an operator-started session, and
        # live builds write it constantly. Re-proving the applied history
        # against a database carrying one must stay green: an entry's
        # invariants are a claim about the schema, not about the rows.
        _register_session_with_no_recorded_request(conn)

        assert (
            verify_applied_history_invariants(
                conn,
                applied,
                history=history,
                load_module=load_module,
                redact=dsn,
            )
            is None
        )
    finally:
        conn.close()
        pg_testdb.drop_test_database(database)


def _register_session_with_no_recorded_request(conn: Any) -> None:
    """Insert a session carrying a served model and no requested model."""
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (1, 'invariant-probe', 'Invariant probe', %s)",
        (now,),
    )
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "session-with-no-recorded-request",
            "claude-code",
            "anthropic",
            "claude-opus-5",
            "/tmp/workspace",
            1,
            now,
            now,
        ),
    )
    conn.commit()
