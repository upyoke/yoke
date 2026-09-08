"""Local universe setup while the surrounding CLI marked a remote plane."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import local_universe_setup as setup
from yoke_contracts.control_plane_locality import (
    RemoteControlPlaneConnectionError,
    refuse_direct_connection,
    remote_control_plane,
    remote_control_plane_active,
)
from yoke_core.domain import db_backend, environment_bootstrap, local_universe as lu


def test_pinned_authority_admits_connect_then_restores_remote_mark(monkeypatch):
    monkeypatch.setenv(db_backend.PG_DSN_ENV, "host=/prior user=x dbname=y")
    with remote_control_plane():
        with pytest.raises(RemoteControlPlaneConnectionError):
            refuse_direct_connection("before pin")
        with lu.pinned_authority("host=/pinned user=yoke dbname=yoke"):
            assert remote_control_plane_active() is False
            refuse_direct_connection("local setup")
            assert os.environ[db_backend.PG_DSN_ENV] == (
                "host=/pinned user=yoke dbname=yoke"
            )
        assert remote_control_plane_active() is True
        with pytest.raises(RemoteControlPlaneConnectionError):
            refuse_direct_connection("after pin")
    assert os.environ[db_backend.PG_DSN_ENV] == "host=/prior user=x dbname=y"


def test_pinned_authority_restores_remote_mark_after_failure():
    with remote_control_plane():
        with pytest.raises(RuntimeError, match="bootstrap failed"):
            with lu.pinned_authority("host=/pinned user=yoke dbname=yoke"):
                raise RuntimeError("bootstrap failed")
        assert remote_control_plane_active() is True


class _BirthHarness:
    def __init__(self, monkeypatch, *, already_born: bool, verify_fails: bool = False):
        self.calls = []
        self.remote_during_work = None
        monkeypatch.setattr(lu, "ensure_engine_binaries", lambda emit=None: Path("/b"))
        monkeypatch.setattr(lu, "start", lambda spec, emit: {"running": True})
        monkeypatch.setattr(lu, "is_born", lambda spec: already_born)

        def fake_bootstrap(emit):
            self.calls.append("bootstrap")
            self.remote_during_work = remote_control_plane_active()
            refuse_direct_connection("schema initialization")
            return {"organizations": 1, "actors": 1}

        def fake_verify(emit):
            self.calls.append("verify")
            self.remote_during_work = remote_control_plane_active()
            refuse_direct_connection("sentinel verification")
            if verify_fails:
                raise environment_bootstrap.BootstrapError("sentinel missing")
            return {"organizations": 1, "actors": 1}

        monkeypatch.setattr(environment_bootstrap, "run_bootstrap", fake_bootstrap)
        monkeypatch.setattr(environment_bootstrap, "verify_bootstrap", fake_verify)
        monkeypatch.setattr(
            lu, "_ensure_org_card", lambda org_name, emit: {"slug": "default"}
        )
        monkeypatch.setattr(lu, "_ensure_human_actor", lambda emit: 7)


def test_birth_create_opens_owned_cluster_while_remote_marked(monkeypatch):
    harness = _BirthHarness(monkeypatch, already_born=False)
    with remote_control_plane():
        report = lu.birth(org_name="Remote Org", emit=lambda _l: None)
    assert report["born"] is True
    assert harness.calls == ["bootstrap"]
    assert harness.remote_during_work is False
    assert remote_control_plane_active() is False


def test_birth_verify_and_repair_open_owned_cluster_while_remote_marked(monkeypatch):
    harness = _BirthHarness(monkeypatch, already_born=True, verify_fails=True)
    with remote_control_plane():
        report = lu.birth(org_name=None, emit=lambda _l: None)
    assert report["repaired"] is True
    assert harness.calls == ["verify", "bootstrap"]
    assert harness.remote_during_work is False


def test_birth_under_remote_plane_bootstraps_real_schema(monkeypatch):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_helpers

    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    monkeypatch.setattr(lu, "ensure_engine_binaries", lambda emit=None: Path("/bin"))
    monkeypatch.setattr(lu, "start", lambda spec, emit: {"running": True})
    monkeypatch.setattr(lu, "local_dsn", lambda spec=None: dsn)
    try:
        with remote_control_plane():
            first = lu.birth(org_name="Remote Org", emit=lambda _l: None)
        assert first["born"] is True
        assert first["verified"]["organizations"] >= 1
        assert remote_control_plane_active() is False
        with remote_control_plane():
            with lu.pinned_authority(dsn):
                conn = db_helpers.connect()
                try:
                    conn.execute("DELETE FROM capability_templates")
                    conn.commit()
                finally:
                    conn.close()
            rerun = lu.birth(org_name=None, emit=lambda _l: None)
        assert rerun["repaired"] is True
        assert rerun["verified"]["capability_templates"] >= 1
        assert remote_control_plane_active() is False
    finally:
        pg_testdb.drop_test_database(name)


def test_run_local_init_names_remote_connection_refusal(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))

    def boom(*, org_name, emit):
        raise RemoteControlPlaneConnectionError(
            "db_backend.connect() cannot open the active control plane"
        )

    monkeypatch.setattr(setup, "_engine", lambda: SimpleNamespace(birth=boom))
    with pytest.raises(setup.LocalUniverseSetupError) as raised:
        setup.run_local_init()
    message = str(raised.value)
    assert "db_backend.connect()" in message
    assert "yoke init --local" in message
    assert "active remote connection" in message
