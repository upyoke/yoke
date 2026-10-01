"""Review databases follow the serving build's boot schema, including history."""

from contextlib import nullcontext

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.tools import serve_workbench_for_review as review
from yoke_contracts.schema_authority import serving_build_authority
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.schema_init import converge_core_schema


@pytest.fixture
def review_databases():
    names = [pg_testdb.create_test_database() for _ in range(2)]
    connections = [pg_testdb.connect_test_database(name) for name in names]
    try:
        yield names, connections
    finally:
        for connection in connections:
            connection.close()
        for name in names:
            pg_testdb.drop_test_database(name)


def _schema_rows(conn):
    return (
        conn.execute("""
        SELECT table_name, column_name, data_type, is_nullable,
               column_default, is_identity, identity_generation
        FROM information_schema.columns WHERE table_schema = 'public'
        ORDER BY table_name, column_name
    """).fetchall(),
        conn.execute("""
        SELECT c.relname, con.conname, pg_get_constraintdef(con.oid)
        FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' ORDER BY c.relname, con.conname
    """).fetchall(),
        conn.execute("""
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' ORDER BY tablename, indexname
    """).fetchall(),
        conn.execute("""
        SELECT viewname, definition FROM pg_views
        WHERE schemaname = 'public' ORDER BY viewname
    """).fetchall(),
    )


def _schema_shape(conn):
    return tuple(tuple(tuple(row) for row in rows) for rows in _schema_rows(conn))


def test_review_schema_matches_fresh_boot_and_repairs_drift(
    monkeypatch,
    review_databases,
):
    names, (fixture, fresh) = review_databases
    monkeypatch.setattr(review, "serving_connection", lambda: ("review", None))
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(fixture))
    monkeypatch.setattr(
        db_backend,
        "resolve_pg_dsn",
        lambda: pg_testdb.dsn_for_test_database(names[0]),
    )
    with serving_build_authority():
        converge_core_schema(
            fresh,
            backup_target_dsn=pg_testdb.dsn_for_test_database(names[1]),
        )
    from yoke_core.domain import migrations, migration_history
    from yoke_core.domain.org_schema import seed_default_org

    history = migration_history.ordered_entries(
        migration_history.history_dir(migrations)
    )
    standalone = next(
        entry for entry in history if "standalone_qa_plan_execution" in entry.name
    )
    # Model an aged universe that has not received the standalone history entry.
    with monkeypatch.context() as older_build:
        older_build.setattr(
            migration_history,
            "ordered_entries",
            lambda directory: tuple(entry for entry in history if entry != standalone),
        )
        review.prepare_review_database()
    seed_default_org(fixture)
    seed_default_org(fresh)
    fixture.commit()
    fresh.commit()
    expected = _schema_shape(fresh)
    actual = _schema_shape(fixture)
    assert actual == expected, [
        (
            part,
            [row for row in got if row not in wanted],
            [row for row in wanted if row not in got],
        )
        for part, (got, wanted) in enumerate(zip(actual, expected))
        if got != wanted
    ]

    fixture.execute(
        "ALTER TABLE qa_requirements DROP COLUMN standalone_execution_id CASCADE"
    )
    fixture.commit()
    assert _schema_shape(fixture) != expected
    review.prepare_review_database()
    actual = _schema_shape(fixture)
    assert actual == expected, [
        (
            part,
            [row for row in got if row not in wanted],
            [row for row in wanted if row not in got],
        )
        for part, (got, wanted) in enumerate(zip(actual, expected))
        if got != wanted
    ]

    from yoke_core.domain.migration_boot_apply import pending_entries
    from yoke_core.domain.migration_history import history_dir, ordered_entries
    from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT

    assert (
        pending_entries(
            fixture,
            ordered_entries(history_dir(migrations)),
            YOKE_LEDGER_CONTRACT,
        )
        == ()
    )
    assert (
        fixture.execute(
            "SELECT applied_by FROM applied_migrations WHERE migration_name = %s",
            (standalone.name,),
        ).fetchone()[0]
        == "boot-converge"
    )


@pytest.mark.parametrize("environment", ["remote", "admin"])
def test_review_refuses_unservable_connection_before_convergence(
    monkeypatch,
    environment,
):
    monkeypatch.setattr(
        review,
        "serving_connection",
        lambda: (environment, "select a local, non-production connection"),
    )
    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: pytest.fail("refused connection opened"),
    )
    with pytest.raises(
        review.UiServerError, match="review_database_connection_refused"
    ):
        review.prepare_review_database()


def test_review_convergence_failure_prevents_server_start(monkeypatch, capsys):
    monkeypatch.setattr(review, "serving_connection", lambda: ("review", None))

    def fail():
        raise RuntimeError("history verification failed")

    monkeypatch.setattr("yoke_core.api.server_entrypoint.ensure_core_schema", fail)
    monkeypatch.setattr(review, "serve_ui", lambda **kwargs: pytest.fail("served"))
    monkeypatch.setattr("sys.argv", ["review"])
    with pytest.raises(SystemExit) as outcome:
        review.main()
    assert outcome.value.code == 1
    assert "review_database_convergence_failed" in capsys.readouterr().err


def test_prepare_only_converges_without_serving(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(review, "prepare_review_database", lambda: calls.append("boot"))
    monkeypatch.setattr(review, "serve_ui", lambda **kwargs: pytest.fail("served"))
    monkeypatch.setattr("sys.argv", ["review", "--prepare-only"])
    review.main()
    assert calls == ["boot"]
    assert "review database: converged" in capsys.readouterr().out
