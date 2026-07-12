"""Tests for the empty-environment bootstrap orchestrator."""

from __future__ import annotations

import pytest

from yoke_core.domain import environment_bootstrap
from yoke_core.domain.environment_bootstrap import (
    INIT_MODULE_CHAIN,
    BootstrapError,
    run_init_chain,
)


class _FakeModule:
    def __init__(self, main):
        self.main = main


class TestInitModuleChain:
    def test_db_router_auto_init_aliases_the_same_chain(self):
        from yoke_core.cli import db_router_init

        assert db_router_init._AUTO_INIT_MODULES is INIT_MODULE_CHAIN

    def test_chain_starts_with_schema(self):
        assert INIT_MODULE_CHAIN[0] == "yoke_core.domain.schema"


class TestRunInitChain:
    def _patch_imports(self, monkeypatch, behavior_by_module):
        def fake_import(modname):
            return _FakeModule(behavior_by_module.get(modname, lambda argv: 0))

        monkeypatch.setattr(
            environment_bootstrap.importlib, "import_module", fake_import
        )

    def test_all_modules_invoked_with_init(self, monkeypatch):
        seen = []

        def fake_import(modname):
            return _FakeModule(lambda argv: seen.append((modname, argv)) or 0)

        monkeypatch.setattr(
            environment_bootstrap.importlib, "import_module", fake_import
        )
        run_init_chain(emit=lambda _l: None)
        assert [name for name, _ in seen] == list(INIT_MODULE_CHAIN)
        assert all(argv == ["init"] for _, argv in seen)

    def test_module_exception_names_module(self, monkeypatch):
        failing = INIT_MODULE_CHAIN[3]

        def boom(argv):
            raise ValueError("table missing")

        self._patch_imports(monkeypatch, {failing: boom})
        with pytest.raises(BootstrapError) as exc:
            run_init_chain(emit=lambda _l: None)
        assert failing in str(exc.value)
        assert "table missing" in str(exc.value)

    def test_module_nonzero_exit_names_module(self, monkeypatch):
        failing = INIT_MODULE_CHAIN[1]
        self._patch_imports(monkeypatch, {failing: lambda argv: 3})
        with pytest.raises(BootstrapError) as exc:
            run_init_chain(emit=lambda _l: None)
        assert failing in str(exc.value)
        assert "exited 3" in str(exc.value)

    def test_systemexit_zero_is_success(self, monkeypatch):
        def exits_clean(argv):
            raise SystemExit(0)

        self._patch_imports(
            monkeypatch, {name: exits_clean for name in INIT_MODULE_CHAIN}
        )
        run_init_chain(emit=lambda _l: None)


class TestEventScanRoot:
    def test_prefers_repo_root(self):
        from yoke_core.domain.environment_bootstrap import _event_scan_root

        root = _event_scan_root()
        assert (root / "runtime" / "api").is_dir()

    def test_falls_back_to_server_source_tree(self, monkeypatch, tmp_path):
        """Package installs have no repo root; use the bundle source resolver."""
        from yoke_core.domain import environment_bootstrap as eb

        def _raise(_start=None):
            raise RuntimeError("no repo root")

        bundle_root = tmp_path / "bundle-source"
        bundle_root.mkdir()

        monkeypatch.setattr("yoke_core.api.repo_root.find_repo_root", _raise)
        monkeypatch.setattr(
            "yoke_core.domain.install_bundle.server_tree_root",
            lambda: bundle_root,
        )
        root = eb._event_scan_root()
        assert root == bundle_root


class TestRunBootstrapRealDb:
    def test_bootstraps_empty_db_to_complete_shape(self, tmp_path):
        """THE empty-env proof: a fresh disposable Postgres database reaches
        the complete control-plane shape through run_bootstrap alone."""
        from pathlib import Path

        from runtime.api.fixtures.file_test_db import (
            connect_test_db,
            init_test_db,
        )
        from yoke_core.api.repo_root import find_repo_root

        repo_root = find_repo_root(Path(__file__))
        counts = {}

        def bootstrap():
            counts.update(
                environment_bootstrap.run_bootstrap(
                    repo_root=repo_root, emit=lambda _l: None
                )
            )

        with init_test_db(tmp_path, apply_schema=bootstrap) as db_path:
            assert counts["roles"] >= 4
            assert counts["permissions"] >= 10
            assert counts["organizations"] >= 1
            assert counts["event_registry"] >= 1
            assert counts["capability_templates"] >= 1
            # A fresh universe seeds NO project rows — projects enter
            # through onboarding — so the projects family and the
            # project-scoped flow rows start empty.
            assert counts["projects"] == 0
            assert counts["designs"] == 0
            assert counts["sites"] == 0
            assert counts["deployment_flows"] == 0
            conn = connect_test_db(db_path)
            try:
                registry = conn.execute(
                    "SELECT COUNT(*) FROM event_registry "
                    "WHERE event_name = 'DeploymentEnvironmentBootstrapped'"
                ).fetchone()
                assert registry[0] == 1
            finally:
                conn.close()


class TestUniverseIsBorn:
    """The one DSN-level born-ness probe (shared by the local universe and
    the API server's first-boot check)."""

    def test_empty_then_born_database(self):
        from runtime.api.fixtures import pg_testdb
        from yoke_core.domain.environment_bootstrap import universe_is_born
        from yoke_core.domain.org_schema import (
            create_org_tables,
            seed_default_org,
        )

        name = pg_testdb.create_test_database()
        dsn = pg_testdb.dsn_for_test_database(name)
        try:
            assert universe_is_born(dsn) is False  # no tables at all

            conn = pg_testdb.connect_test_database(name)
            try:
                conn.execute("CREATE TABLE actors (id SERIAL PRIMARY KEY)")
                conn.execute("CREATE TABLE roles (id SERIAL PRIMARY KEY)")
                conn.execute("CREATE TABLE projects (id SERIAL PRIMARY KEY, slug TEXT)")
                create_org_tables(conn)
                assert universe_is_born(dsn) is False  # table exists, no card
                seed_default_org(conn)
            finally:
                conn.close()
            assert universe_is_born(dsn) is True
        finally:
            pg_testdb.drop_test_database(name)

    def test_unreachable_database_reads_as_not_born(self):
        from yoke_core.domain.environment_bootstrap import universe_is_born

        assert (
            universe_is_born(
                "host=127.0.0.1 port=9 user=nobody dbname=absent connect_timeout=1"
            )
            is False
        )

    def test_local_universe_probe_delegates_to_shared_probe(self, monkeypatch):
        from yoke_core.domain import environment_bootstrap as eb
        from yoke_core.domain import local_universe as lu

        seen = {}

        def fake_probe(dsn):
            seen["dsn"] = dsn
            return True

        monkeypatch.setattr(eb, "universe_is_born", fake_probe)
        monkeypatch.setattr(lu, "local_dsn", lambda spec=None: "host=/x dbname=yoke")
        assert lu.is_born() is True
        assert seen["dsn"] == "host=/x dbname=yoke"


class TestMain:
    def test_rejects_arguments(self, capsys):
        assert environment_bootstrap.main(["unexpected"]) == 2
        assert "Usage" in capsys.readouterr().err

    def test_bootstrap_error_exits_one(self, monkeypatch, capsys):
        def boom(repo_root=None, emit=None):
            raise BootstrapError("init module x exited 3")

        monkeypatch.setattr(environment_bootstrap, "run_bootstrap", boom)
        assert environment_bootstrap.main([]) == 1
        assert "init module x" in capsys.readouterr().err
