"""Tests for the embedded local-universe engine surface."""

from __future__ import annotations

import getpass
import os
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import actors
from yoke_core.domain import db_backend
from yoke_core.domain import environment_bootstrap
from yoke_core.domain import local_universe as lu
from yoke_core.domain import postgres_cluster


def _completed(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_universe_root_lives_under_machine_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    assert lu.universe_root() == tmp_path / "machine-home" / "local-universe"


def test_cluster_spec_is_durable_and_socket_scoped(tmp_path):
    spec = lu.cluster_spec(root=tmp_path / "u", bin_dir=tmp_path / "engine" / "bin")

    assert spec.superuser == "yoke"
    assert spec.stop_mode == "fast"  # durable data: checkpoint on stop
    assert spec.server_settings == ()  # no throwaway durability tuning
    assert spec.bin_dir == tmp_path / "engine" / "bin"
    assert lu.local_dsn(spec) == f"host={spec.sock_dir} user=yoke dbname=yoke"


def test_cluster_spec_shortens_overlong_unix_socket_path(tmp_path):
    root = tmp_path / ("nested-machine-home-" * 8) / "local-universe"
    spec = lu.cluster_spec(root=root)
    socket_path = spec.sock_dir / f".s.PGSQL.{postgres_cluster.SOCKET_PORT}"

    assert spec.root == root
    assert spec.socket_dir is not None
    assert spec.sock_dir != root / "sock"
    assert len(os.fsencode(socket_path)) <= lu._MAX_POSTGRES_SOCKET_PATH_BYTES
    assert lu.local_dsn(spec) == f"host={spec.sock_dir} user=yoke dbname=yoke"


def test_socket_path_at_platform_limit_stays_with_cluster_root():
    socket_name = f".s.PGSQL.{postgres_cluster.SOCKET_PORT}"
    suffix_size = len(os.fsencode(f"/sock/{socket_name}"))
    root_size = lu._MAX_POSTGRES_SOCKET_PATH_BYTES - suffix_size
    root = Path("/" + ("r" * (root_size - 1)))

    assert len(os.fsencode(root / "sock" / socket_name)) == (
        lu._MAX_POSTGRES_SOCKET_PATH_BYTES
    )
    assert lu._socket_dir_for_root(root) is None
    assert lu._socket_dir_for_root(Path(f"{root}x")) is not None


def test_socket_fallback_skips_unwritable_shorter_root(monkeypatch, tmp_path):
    long_root = tmp_path / ("nested-machine-home-" * 8) / "local-universe"
    with lu.tempfile.TemporaryDirectory(
        prefix="yoke-fallback-test-", dir="/tmp"
    ) as short_temp:
        preferred = Path(short_temp)
        monkeypatch.setattr(lu.tempfile, "gettempdir", lambda: str(preferred))
        original_access = lu.os.access
        monkeypatch.setattr(
            lu.os,
            "access",
            lambda path, mode: (
                False if Path(path) == Path("/tmp") else original_access(path, mode)
            ),
        )

        assert lu._socket_dir_for_root(long_root).parent == preferred


def test_birth_reports_prior_socket_dsn_for_same_cluster(monkeypatch, tmp_path):
    root = tmp_path / ("nested-machine-home-" * 8) / "local-universe"
    spec = lu.cluster_spec(root=root)

    assert spec.socket_dir is not None
    assert lu._socket_dsn_aliases(spec) == [
        f"host={root / 'sock'} user=yoke dbname=yoke"
    ]


def test_ensure_database_creates_once(monkeypatch, tmp_path):
    spec = lu.cluster_spec(root=tmp_path / "u")
    statements = []

    def fake_psql(_spec, sql, dbname="postgres"):
        statements.append(sql)
        if sql.startswith("SELECT"):
            return _completed("" if len(statements) == 1 else "1")
        return _completed()

    monkeypatch.setattr(postgres_cluster, "psql", fake_psql)

    lu.ensure_database(spec)  # absent -> CREATE DATABASE
    lu.ensure_database(spec)  # present -> probe only

    creates = [sql for sql in statements if sql.startswith("CREATE DATABASE")]
    assert creates == ['CREATE DATABASE "yoke"']


def test_pinned_authority_sets_and_restores_dsn(monkeypatch):
    monkeypatch.setenv(db_backend.PG_DSN_ENV, "host=/prior user=x dbname=y")
    with lu.pinned_authority("host=/pinned user=yoke dbname=yoke"):
        assert os.environ[db_backend.PG_DSN_ENV] == (
            "host=/pinned user=yoke dbname=yoke"
        )
    assert os.environ[db_backend.PG_DSN_ENV] == "host=/prior user=x dbname=y"


class _BirthHarness:
    """Monkeypatched engine pieces recording birth orchestration order."""

    def __init__(self, monkeypatch, *, already_born: bool, verify_fails: bool = False):
        self.calls = []
        self.dsn_at_bootstrap = None
        self.label_env_at_bootstrap = None
        monkeypatch.setattr(
            lu,
            "ensure_engine_binaries",
            lambda emit=None: self.calls.append("binaries") or Path("/nowhere/bin"),
        )
        monkeypatch.setattr(
            lu,
            "start",
            lambda spec, emit: self.calls.append("start") or {"running": True},
        )
        monkeypatch.setattr(lu, "is_born", lambda spec: already_born)

        def fake_bootstrap(emit):
            self.calls.append("bootstrap")
            self.dsn_at_bootstrap = os.environ.get(db_backend.PG_DSN_ENV)
            self.label_env_at_bootstrap = os.environ.get(actors.LOCAL_HUMAN_LABEL_ENV)
            return {"organizations": 1, "actors": 1}

        def fake_verify(emit):
            self.calls.append("verify")
            if verify_fails:
                raise environment_bootstrap.BootstrapError(
                    "verification failed: sentinel table missing"
                )
            return {"organizations": 1, "actors": 1}

        monkeypatch.setattr(environment_bootstrap, "run_bootstrap", fake_bootstrap)
        monkeypatch.setattr(environment_bootstrap, "verify_bootstrap", fake_verify)
        monkeypatch.setattr(
            lu,
            "_ensure_org_card",
            lambda org_name, emit: (
                self.calls.append(("org", org_name))
                or {"slug": "default", "name": org_name or "Default Org"}
            ),
        )
        monkeypatch.setattr(
            lu,
            "_ensure_human_actor",
            lambda emit: self.calls.append("human") or 7,
        )


def test_birth_bootstraps_fresh_universe_under_pinned_dsn(monkeypatch):
    harness = _BirthHarness(monkeypatch, already_born=False)

    report = lu.birth(org_name="Proof Org", emit=lambda _l: None)

    assert report["born"] is True
    assert report["repaired"] is False
    assert report["verified"] == {"organizations": 1, "actors": 1}
    assert report["org"] == {"slug": "default", "name": "Proof Org"}
    assert report["human_actor_id"] == 7
    assert harness.calls == [
        "binaries",
        "start",
        "bootstrap",
        ("org", "Proof Org"),
        "human",
    ]
    assert harness.dsn_at_bootstrap == report["dsn"]
    assert "dbname=yoke" in report["dsn"]
    # The universe owner's OS login rides the pinned env injection so the
    # init chain's canonical-actor seeding labels the human actor with it.
    assert harness.label_env_at_bootstrap == getpass.getuser()


def test_birth_verifies_live_universe_without_rebootstrapping(monkeypatch):
    harness = _BirthHarness(monkeypatch, already_born=True)

    report = lu.birth(org_name=None, emit=lambda _l: None)

    assert report["born"] is False
    assert report["repaired"] is False
    assert report["verified"] == {"organizations": 1, "actors": 1}
    assert harness.calls == ["binaries", "start", "verify", ("org", None), "human"]


def test_birth_repairs_live_universe_that_fails_verification(monkeypatch):
    harness = _BirthHarness(monkeypatch, already_born=True, verify_fails=True)

    report = lu.birth(org_name=None, emit=lambda _l: None)

    assert report["born"] is False
    assert report["repaired"] is True
    assert report["verified"] == {"organizations": 1, "actors": 1}
    assert harness.calls == [
        "binaries",
        "start",
        "verify",
        "bootstrap",
        ("org", None),
        "human",
    ]


def test_ensure_org_card_seeds_then_renames(test_db):
    card = lu._ensure_org_card(None, lambda _l: None)
    assert card["slug"] == "default"

    renamed = lu._ensure_org_card("My Local Org", lambda _l: None)
    assert renamed == {"slug": "default", "name": "My Local Org"}

    count = test_db.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    assert int(count) == 1  # identity card stays single-row


def test_ensure_human_actor_seeds_once(test_db):
    test_db.execute("DELETE FROM actor_labels")
    test_db.execute("DELETE FROM actors WHERE kind = 'human'")
    test_db.commit()

    first = lu._ensure_human_actor(lambda _l: None)
    second = lu._ensure_human_actor(lambda _l: None)

    assert first == second
    count = test_db.execute(
        "SELECT COUNT(*) FROM actors WHERE kind = 'human'"
    ).fetchone()[0]
    assert int(count) == 1


def test_status_reports_stopped_universe(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.setattr(postgres_cluster, "is_ready", lambda spec: False)

    payload = lu.status()

    assert payload["running"] is False
    assert payload["initialized"] is False
    assert "dsn" not in payload
    assert payload["root"] == str(tmp_path / "machine-home" / "local-universe")


def _initialized_universe_without_binaries(monkeypatch, tmp_path) -> None:
    """Data dir present, embedded binaries absent, no Postgres on PATH."""
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    data_dir = tmp_path / "machine-home" / "local-universe" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "no-binaries-here"))


def test_status_raises_typed_error_when_binaries_missing(monkeypatch, tmp_path):
    _initialized_universe_without_binaries(monkeypatch, tmp_path)

    with pytest.raises(lu.LocalUniverseError) as excinfo:
        lu.status()

    message = str(excinfo.value)
    assert "embedded Postgres binaries are missing" in message
    assert str(tmp_path / "machine-home" / "postgres") in message
    assert "yoke local-postgres start" in message


def test_stop_raises_typed_error_when_binaries_missing(monkeypatch, tmp_path):
    _initialized_universe_without_binaries(monkeypatch, tmp_path)

    with pytest.raises(lu.LocalUniverseError) as excinfo:
        lu.stop()

    assert "embedded Postgres binaries are missing" in str(excinfo.value)
    assert "refetch" in str(excinfo.value)


def test_run_bootstrap_seeds_human_actor_with_injected_label(tmp_path, monkeypatch):
    """The REAL init chain (no mocking of the actor step) honors the label
    injection the birth path pins for a fresh universe."""
    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
    from yoke_core.api.repo_root import find_repo_root

    monkeypatch.setenv(actors.LOCAL_HUMAN_LABEL_ENV, "composition-owner")
    repo_root = find_repo_root(Path(__file__))

    def bootstrap():
        environment_bootstrap.run_bootstrap(repo_root=repo_root, emit=lambda _l: None)

    with init_test_db(tmp_path, apply_schema=bootstrap) as db_path:
        conn = connect_test_db(db_path)
        try:
            labels = [
                row[0]
                for row in conn.execute(
                    "SELECT al.label FROM actors a "
                    "JOIN actor_labels al ON al.actor_id = a.id "
                    "WHERE a.kind = 'human'"
                ).fetchall()
            ]
        finally:
            conn.close()
    assert labels == ["composition-owner"]


def test_birth_composition_labels_os_login_and_repairs_half_born(monkeypatch):
    """End-to-end birth against a REAL fresh database (cluster seams stubbed):
    the fresh birth runs the real bootstrap and labels the human actor with
    the OS login; emptying a sentinel table afterwards simulates a half-born
    universe, and the re-run detects it via verification and repairs it."""
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_helpers

    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    monkeypatch.setattr(
        lu,
        "ensure_engine_binaries",
        lambda emit=None: Path("/unused-bin"),
    )
    monkeypatch.setattr(lu, "start", lambda spec, emit: {"running": True})
    monkeypatch.setattr(lu, "local_dsn", lambda spec=None: dsn)
    try:
        first = lu.birth(org_name="Composition Org", emit=lambda _l: None)
        assert first["born"] is True
        assert first["repaired"] is False
        assert first["verified"]["organizations"] >= 1
        assert first["org"]["name"] == "Composition Org"

        with lu.pinned_authority(dsn):
            conn = db_helpers.connect()
            try:
                labels = [
                    row[0]
                    for row in conn.execute(
                        "SELECT al.label FROM actors a "
                        "JOIN actor_labels al ON al.actor_id = a.id "
                        "WHERE a.kind = 'human'"
                    ).fetchall()
                ]
                # Simulate a first-run crash after the org card landed but
                # before vocabulary seeding: empty a seeded sentinel table.
                conn.execute("DELETE FROM capability_templates")
                conn.commit()
            finally:
                conn.close()
        assert labels == [getpass.getuser()]

        rerun = lu.birth(org_name=None, emit=lambda _l: None)
        assert rerun["born"] is False  # liveness probe still sees the org card
        assert rerun["repaired"] is True  # verification caught the gap
        assert rerun["verified"]["capability_templates"] >= 1
        assert rerun["human_actor_id"] == first["human_actor_id"]
    finally:
        pg_testdb.drop_test_database(name)
