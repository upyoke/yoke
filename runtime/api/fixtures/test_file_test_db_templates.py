"""Schema callable templates preserve seeds, isolation and build failures."""

import os
import json
import contextlib
import importlib
import random
from pathlib import Path

import pytest

from runtime.api.fixtures import file_test_db, pg_reusable_db, pg_testdb
from yoke_core.domain import db_backend, schema


def _rows():
    with db_backend.connect_psycopg() as conn:
        return conn.execute("SELECT id FROM template_seed ORDER BY id").fetchall()


def _strategy(builds):
    def apply():
        builds.append(True)
        with db_backend.connect_psycopg() as conn:
            conn.execute("CREATE TABLE template_seed (id INTEGER)")
            conn.execute("INSERT INTO template_seed VALUES (7)")

    return apply


def test_custom_callable_builds_once_and_restores_seed_rows(tmp_path):
    builds = []
    apply = _strategy(builds)
    with file_test_db.init_test_db(tmp_path, apply):
        with db_backend.connect_psycopg() as conn:
            first = conn.execute("SELECT current_database()").fetchone()[0]
            conn.execute("DELETE FROM template_seed")
    with file_test_db.init_test_db(tmp_path, apply):
        assert _rows() == [(7,)]
        with db_backend.connect_psycopg() as conn:
            assert conn.execute("SELECT current_database()").fetchone()[0] == first
    assert builds == [True]


@pytest.mark.parametrize(
    "module_name,fixture_name",
    [
        ("test_sessions", "conn"),
        ("test_sessions", "ownership_conn"),
        ("sessions_api_stale_test_helpers", "conn"),
        ("sessions_api_stale_test_helpers", "ownership_conn"),
        ("test_sessions_reactivation_driver_stamp", "conn"),
        ("test_field_note_provenance", "isolated_db"),
        ("test_work_claim_active_uniques", "_bootstrap_db"),
    ],
)
def test_session_consumers_bind_machine_after_cached_checkout(
    tmp_path, monkeypatch, module_name, fixture_name
):
    """Reuse each consumer's first callback under fresh homes in shuffled order."""
    from yoke_contracts.machine_config.schema_connections import operating_actor_binding
    from yoke_core.domain.universe_identity import universe_fingerprint

    module = importlib.import_module(f"runtime.api.{module_name}")
    strategy = None
    builds = []

    def apply():
        builds.append(True)
        strategy()

    @contextlib.contextmanager
    def checkout(path, apply_schema=file_test_db.apply_test_schema):
        nonlocal strategy
        if strategy is None:
            strategy = apply_schema
        with file_test_db.init_test_db(path, apply):
            # A template must contain database state, never machine configuration.
            assert not (Path(os.environ["YOKE_MACHINE_HOME"]) / "config.json").exists()
            yield str(path / "yoke.db")

    monkeypatch.setattr(module, "init_test_db", checkout)
    order = list(range(3))
    random.Random(23).shuffle(order)
    for index in order:
        with monkeypatch.context() as scoped:
            home = tmp_path / f"machine-{index}"
            workspace = tmp_path / f"workspace-{index}"
            workspace.mkdir()
            scoped.setenv("YOKE_MACHINE_HOME", str(home))
            scoped.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
            args = (
                (workspace, scoped) if fixture_name == "isolated_db" else (workspace,)
            )
            fixture = getattr(module, fixture_name).__wrapped__(*args)
            try:
                next(fixture)
                payload = json.loads((home / "config.json").read_text())
                actor_id, universe = operating_actor_binding(payload, "local")
                with db_backend.connect_psycopg() as conn:
                    assert universe == universe_fingerprint(conn)
                    assert conn.execute(
                        "SELECT kind FROM actors WHERE id = %s", (actor_id,)
                    ).fetchone() == ("human",)
            finally:
                fixture.close()
    assert builds == [True]


def test_nested_custom_context_and_ddl_drift_clone_without_rebuilding(tmp_path):
    builds = []
    apply = _strategy(builds)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    with file_test_db.init_test_db(tmp_path, apply):
        outer = os.environ[db_backend.PG_DSN_ENV]
        with file_test_db.init_test_db(tmp_path, apply):
            assert os.environ[db_backend.PG_DSN_ENV] != outer
            assert _rows() == [(7,)]
            with db_backend.connect_psycopg() as conn:
                conn.execute("DELETE FROM template_seed")
        assert os.environ[db_backend.PG_DSN_ENV] == outer
        assert _rows() == [(7,)]
        with db_backend.connect_psycopg() as conn:
            conn.execute("DROP TABLE template_seed")
    with file_test_db.init_test_db(tmp_path, apply):
        assert _rows() == [(7,)]
    assert builds == [True]
    assert os.environ.get(db_backend.PG_DSN_ENV) == prior


def test_distinct_same_named_callables_have_distinct_templates(tmp_path):
    first_builds, second_builds = [], []
    first, second = _strategy(first_builds), _strategy(second_builds)
    assert first.__qualname__ == second.__qualname__
    with file_test_db.init_test_db(tmp_path, first):
        first_dsn = os.environ[db_backend.PG_DSN_ENV]
    with file_test_db.init_test_db(tmp_path, second):
        assert os.environ[db_backend.PG_DSN_ENV] != first_dsn
    assert first_builds == second_builds == [True]


def test_unhashable_callable_uses_identity(tmp_path):
    class Strategy:
        __hash__ = None

        def __init__(self):
            self.builds = []

        def __call__(self):
            _strategy(self.builds)()

    apply = Strategy()
    for _ in range(2):
        with file_test_db.init_test_db(tmp_path, apply):
            assert _rows() == [(7,)]
    assert apply.builds == [True]


def test_failed_template_is_dropped_and_restores_dsn(tmp_path, monkeypatch):
    builds, dropped = [], []
    apply = _strategy(builds)
    original = pg_testdb.drop_test_database

    def drop(name, **kwargs):
        dropped.append(name)
        return original(name, **kwargs)

    monkeypatch.setattr(pg_testdb, "drop_test_database", drop)
    prior = os.environ.get(db_backend.PG_DSN_ENV)

    def failing():
        apply()
        raise RuntimeError("schema build refused")

    with pytest.raises(RuntimeError, match="schema build refused"):
        with file_test_db.init_test_db(tmp_path, failing):
            pytest.fail("failed schema must never be yielded")
    assert len(dropped) == 1
    assert id(failing) not in file_test_db._SCHEMA_TEMPLATES
    assert os.environ.get(db_backend.PG_DSN_ENV) == prior


def test_explicit_production_init_shares_default_flavor(tmp_path):
    with file_test_db.init_test_db(tmp_path):
        first = os.environ[db_backend.PG_DSN_ENV]
    with file_test_db.init_test_db(tmp_path, schema.cmd_init):
        assert os.environ[db_backend.PG_DSN_ENV] == first


def test_production_strategy_is_reused_and_resets_actor_data(tmp_path):
    from runtime.api.fixtures.file_test_db import apply_test_schema

    with file_test_db.init_test_db(tmp_path, apply_test_schema):
        first = os.environ[db_backend.PG_DSN_ENV]
        with db_backend.connect_psycopg() as conn:
            baseline = conn.execute(
                "SELECT id, name FROM actors ORDER BY id"
            ).fetchall()
            assert baseline
            conn.execute("UPDATE actors SET name = 'changed'")
    with file_test_db.init_test_db(tmp_path, apply_test_schema):
        assert os.environ[db_backend.PG_DSN_ENV] == first
        with db_backend.connect_psycopg() as conn:
            assert (
                conn.execute("SELECT id, name FROM actors ORDER BY id").fetchall()
                == baseline
            )
    pg_reusable_db.discard(id(file_test_db._apply_production_schema))


def test_cached_session_schema_records_each_fresh_machine_home(tmp_path, monkeypatch):
    from runtime.api import test_service_client_sessions_helpers as sessions
    from yoke_contracts.machine_config.schema_connections import operating_actor_binding

    builds = []
    original = sessions._apply_session_schema

    def apply():
        builds.append(True)
        original()

    monkeypatch.setattr(sessions, "_apply_session_schema", apply)
    for index in range(2):
        with monkeypatch.context() as scoped:
            home = tmp_path / f"machine-{index}"
            workspace = tmp_path / f"workspace-{index}"
            workspace.mkdir()
            scoped.setenv("YOKE_MACHINE_HOME", str(home))
            scoped.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
            fixture = sessions.session_test_db.__wrapped__(workspace, scoped)
            try:
                next(fixture)
                payload = json.loads((home / "config.json").read_text())
                actor_id, universe = operating_actor_binding(payload, "local")
                assert actor_id is not None and universe
            finally:
                fixture.close()
    assert builds == [True]
