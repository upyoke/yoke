"""Permanent contracts for re-proving shipped migration invariants."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.tools.yoke_migration_rehearsal import (
    converge,
    history_names,
    load_module,
    pending_names,
)
from yoke_contracts.session_control.relay_health import sanitize_relay_health
from yoke_core.domain import db_backend, environment_bootstrap
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.migration_fleet_applied_invariants import (
    RETIRED_STANDING_INVARIANTS,
    applied_shipped_names,
    format_fleet_summary,
    skipped_standing_invariant_line,
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

    report = verify_applied_history_invariants(
        object(),
        ("0001_presence",),
        history=tuple(modules),
        load_module=modules.__getitem__,
    )

    assert report.failure is None
    assert report.skipped == ()


def test_retired_standing_invariant_names_its_skip_and_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    name, reason = next(iter(RETIRED_STANDING_INVARIANTS.items()))

    def wrong_standing_invariant(_conn: Any) -> None:
        raise AssertionError("this invariant must be skipped")

    report = verify_applied_history_invariants(
        object(),
        (name,),
        history=(name,),
        load_module=lambda _name: SimpleNamespace(invariants=wrong_standing_invariant),
    )

    assert report.failure is None
    assert report.skipped == ((name, reason),)
    assert capsys.readouterr().out == (
        f"converging {name}: standing invariant skipped -- {reason}\n"
    )


def test_fleet_summary_names_skipped_standing_invariants_beside_pass_fail() -> None:
    name, reason = next(iter(RETIRED_STANDING_INVARIANTS.items()))
    passed = SimpleNamespace(passed=True, skipped_invariants=((name, reason),))
    failed = SimpleNamespace(passed=False, skipped_invariants=())

    summary = format_fleet_summary((passed, passed, failed))

    assert summary.splitlines()[0] == "2 passed, 1 failed, 1 skipped"
    assert skipped_standing_invariant_line(name, reason) in summary.splitlines()
    assert (
        format_fleet_summary((SimpleNamespace(passed=True, skipped_invariants=()),))
        == "1 passed, 0 failed, 0 skipped"
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
        first = verify_applied_history_invariants(
            conn,
            applied,
            history=history,
            load_module=load_module,
            redact=dsn,
        )
        assert first.failure is None
        assert "0035_clear_unproven_onboard_activation_latch" in dict(first.skipped)
        assert "0070_native_domain_instants" in dict(first.skipped)

        # Every live relay heartbeat stores this health shape, which frozen
        # 0070 rejects; the re-prover must name that skip and stay green.
        _store_live_relay_health(conn)
        with pytest.raises(AssertionError, match="mutable_instant_not_canonical"):
            load_module("0070_native_domain_instants").invariants(conn)
        conn.rollback()

        # A session whose provider attested a model but whose ask was never
        # recorded is the normal shape of an manually started session, and
        # live builds write it constantly. Re-proving the applied history
        # against a database carrying one must stay green: an entry's
        # invariants are a claim about the schema, not about the rows.
        _register_session_with_no_recorded_request(conn)

        second = verify_applied_history_invariants(
            conn,
            applied,
            history=history,
            load_module=load_module,
            redact=dsn,
        )
        assert second.failure is None
    finally:
        conn.close()
        pg_testdb.drop_test_database(database)


def _store_live_relay_health(conn: Any) -> None:
    """Insert a relay whose health is the live writer's no-failure document."""
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO actors (id, kind, name, created_at) "
        "VALUES (900, 'human', 'Relay owner', %s)",
        (now,),
    )
    conn.execute(
        "INSERT INTO session_relays ("
        "relay_id, actor_id, machine_id, hostname, surface_versions, "
        "project_checkouts, first_seen_at, last_seen_at, connected_until, "
        "relay_health"
        ") VALUES ('machine:probe', 900, 'probe', 'probe', '{}', '[]', "
        "%s, %s, %s, %s)",
        (now, now, now, dumps_compact(sanitize_relay_health({}))),
    )
    conn.commit()


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


def test_model_effort_levels_reproof_accepts_a_missing_quota_order_row() -> None:
    """A missing quota-order row is valid; a present row must be the two pools."""
    import importlib
    import json
    import sqlite3

    name = "0071_model_effort_levels"
    module = importlib.import_module(
        "yoke_core.domain.migrations.0071_model_effort_levels"
    )
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE universe_settings ("
        "key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, "
        "updated_by_actor_id INTEGER)"
    )

    def load(loaded: str) -> Any:
        assert loaded == name
        return module

    def reprove() -> Any:
        return verify_applied_history_invariants(
            conn,
            (name,),
            history=(name,),
            load_module=load,
        )

    assert reprove().failure is None
    conn.execute(
        "INSERT INTO universe_settings (key, value) VALUES ('cursor_quota_order', ?)",
        (json.dumps(["Cursor Models", "Other Models"]),),
    )
    assert reprove().failure is None
    conn.execute(
        "UPDATE universe_settings SET value = ? WHERE key = 'cursor_quota_order'",
        (json.dumps(["Cursor Models"]),),
    )
    failure = reprove().failure
    assert failure is not None
    assert failure.startswith(f"{name} invariants failed --")
    assert "Recovery:" in failure
