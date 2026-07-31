"""Tests for the disposable local Postgres cluster frontend.

The initdb/pg_ctl choreography itself is covered by
``runtime/api/domain/test_postgres_cluster.py``; these tests pin the
disposable frontend's spec (system binaries, throwaway tuning, scratch
root) and its ownership-gated orphan sweep.
"""

from __future__ import annotations

import os
import subprocess

from yoke_core.domain import pg_test_db_namespace, postgres_cluster
from yoke_core.domain.db_backend import POSTGRES_TEST_DB_PREFIX
from yoke_core.tools import pg_testcluster


def _completed(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_spec_uses_disposable_cluster_settings(monkeypatch):
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", "/tmp/yoke-pgtest-spec")

    spec = pg_testcluster._spec()

    assert spec.superuser == pg_testcluster.PGUSER
    assert spec.bin_dir is None  # system binaries from PATH
    assert spec.stop_mode == "immediate"
    settings = dict(spec.server_settings)
    assert settings["max_connections"] == "200"
    assert settings["max_wal_size"] == "512MB"
    assert settings["fsync"] == "off"
    assert settings["full_page_writes"] == "off"

    opts = postgres_cluster.server_options(spec)
    assert "-c max_connections=200" in opts
    assert "-c fsync=off" in opts
    assert "-c listen_addresses=''" in opts


def test_ensure_started_recreates_on_stale_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", str(tmp_path / "cluster"))
    calls = []

    monkeypatch.setattr(
        postgres_cluster, "initdb_if_needed",
        lambda spec: calls.append("initdb") or 0,
    )
    monkeypatch.setattr(
        postgres_cluster, "ensure_started",
        lambda spec: calls.append("start") or 0,
    )
    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_settings_match", lambda: False)
    monkeypatch.setattr(
        pg_testcluster, "destroy", lambda: calls.append("destroy") or 0,
    )

    assert pg_testcluster.ensure_started() == 0
    assert calls == ["initdb", "destroy", "initdb", "start"]


def _name_owned_by(pid: int, purpose: str = "abc") -> str:
    return (
        f"{POSTGRES_TEST_DB_PREFIX}"
        f"{pg_test_db_namespace.mint_run_tag(pid=pid)}_{purpose}"
    )


def _sweep_with(monkeypatch, *, listed: str, live_pids: set[int]):
    """Run the sweep against *listed* names, treating *live_pids* as running."""
    calls = []

    def fake_psql(sql: str, *, statement_timeout_ms=None):
        calls.append(sql)
        if sql.startswith("SELECT"):
            return _completed(listed)
        return _completed()

    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_psql", fake_psql)
    monkeypatch.setattr(
        pg_testcluster, "_owner_process_is_alive", lambda pid: pid in live_pids
    )
    rc = pg_testcluster.sweep_orphaned_test_databases()
    return rc, calls


def test_sweep_reclaims_databases_whose_owner_has_exited(monkeypatch):
    dead_owner = _name_owned_by(4001)

    rc, calls = _sweep_with(monkeypatch, listed=f"{dead_owner}\n", live_pids=set())

    assert rc == 0
    assert any(
        sql.startswith(f'DROP DATABASE IF EXISTS "{dead_owner}"') for sql in calls
    )


def test_sweep_never_touches_a_live_invocations_databases(monkeypatch):
    """This is the invariant that makes concurrent runs safe.

    The previous heuristic — unconnected plus quiet — selected 26 of 30 in-use
    databases against a live suite, because a database created but not yet
    connected to looks idle. Asking the operating system whether the owner is
    still running replaces the guess with a fact.
    """
    live = _name_owned_by(5001)

    rc, calls = _sweep_with(monkeypatch, listed=f"{live}\n", live_pids={5001})

    assert rc == 0
    assert not [sql for sql in calls if sql.startswith("DROP")]


def test_sweep_ignores_databases_outside_the_owner_tagged_namespace(monkeypatch):
    # An operator's migration validation database is test-prefixed but belongs
    # to no invocation; reclaiming it would destroy work in progress.
    untagged = f"{POSTGRES_TEST_DB_PREFIX}sun1234_validation"

    rc, calls = _sweep_with(monkeypatch, listed=f"{untagged}\n", live_pids=set())

    assert rc == 0
    assert not [sql for sql in calls if sql.startswith("DROP")]


def test_sweep_selects_only_tagged_names_old_enough_to_be_orphans(monkeypatch):
    # PIDs get recycled, so the age condition backstops a misread owner.
    _, calls = _sweep_with(monkeypatch, listed="", live_pids=set())

    select = next(sql for sql in calls if sql.startswith("SELECT"))
    assert pg_test_db_namespace.OWNED_DATABASE_LIKE_PATTERN in select
    assert "modification" in select
    assert f"'{pg_testcluster.ORPHAN_TEST_DB_MIN_AGE_MINUTES} minutes'" in select


def test_sweep_measures_age_from_creation_not_directory_activity(monkeypatch):
    """The directory timestamp is not an idleness signal.

    PostgreSQL's checkpointer and autovacuum touch a database's directory for
    their own reasons, so an abandoned database keeps looking freshly used and
    never becomes reclaimable — measured against a live cluster, that signal
    made 0 of 161 known-dead databases eligible while PG_VERSION, which is
    written once at creation and never rewritten, correctly identified 138.
    Reading the wrong file is how a cluster silently accumulates hundreds of
    leaked databases.
    """
    _, calls = _sweep_with(monkeypatch, listed="", live_pids=set())

    select = next(sql for sql in calls if sql.startswith("SELECT"))
    assert "PG_VERSION" in select
    assert "pg_stat_file('base/' || d.oid::text, true)" not in select


def test_sweep_forces_the_drop_under_a_bounded_statement_timeout(monkeypatch):
    # A dead owner can still have leaked a child holding the database open.
    # FORCE evicts it; the timeout keeps a wedged drop from parking the sweep.
    dead_owner = _name_owned_by(6001)
    timeouts = []

    def fake_psql(sql: str, *, statement_timeout_ms=None):
        if sql.startswith("SELECT"):
            return _completed(f"{dead_owner}\n")
        timeouts.append(statement_timeout_ms)
        return _completed()

    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_psql", fake_psql)
    monkeypatch.setattr(
        pg_testcluster, "_owner_process_is_alive", lambda pid: False
    )

    pg_testcluster.sweep_orphaned_test_databases()

    assert timeouts == [pg_testcluster.ORPHAN_DROP_STATEMENT_TIMEOUT_MS]


def test_sweep_continues_past_a_drop_another_sweep_already_won(monkeypatch):
    # Two runs may sweep at once; losing the race is not this run's failure.
    first, second = _name_owned_by(7001), _name_owned_by(7002)
    dropped = []

    def fake_psql(sql: str, *, statement_timeout_ms=None):
        if sql.startswith("SELECT"):
            return _completed(f"{first}\n{second}\n")
        if first in sql:
            return _completed("ERROR: database does not exist", returncode=1)
        dropped.append(sql)
        return _completed()

    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_psql", fake_psql)
    monkeypatch.setattr(
        pg_testcluster, "_owner_process_is_alive", lambda pid: False
    )

    assert pg_testcluster.sweep_orphaned_test_databases() == 0
    assert len(dropped) == 1
    assert second in dropped[0]


def test_sweep_declines_when_database_age_cannot_be_read(monkeypatch, capsys):
    # Falling back to the owner check alone would let a recycled PID condemn a
    # live run's database. Leaving garbage for the next sweep is safer.
    dropped = []

    def fake_psql(sql: str, *, statement_timeout_ms=None):
        if sql.startswith("SELECT"):
            return _completed("permission denied", returncode=1)
        dropped.append(sql)
        return _completed()

    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_psql", fake_psql)

    assert pg_testcluster.sweep_orphaned_test_databases() == 0
    assert dropped == []
    assert "skipping orphan sweep" in capsys.readouterr().err


def test_sweep_reports_what_it_reclaimed(monkeypatch, capsys):
    # A silent sweep let this cluster reach 275 leaked databases unnoticed.
    listed = f"{_name_owned_by(8001)}\n{_name_owned_by(8002)}\n"

    _sweep_with(monkeypatch, listed=listed, live_pids=set())

    assert "reclaimed 2 orphaned test database(s)" in capsys.readouterr().err


def test_sweep_stays_quiet_when_nothing_was_orphaned(monkeypatch, capsys):
    _sweep_with(monkeypatch, listed="", live_pids=set())

    assert capsys.readouterr().err == ""


def test_owner_liveness_reads_the_operating_system(monkeypatch):
    assert pg_testcluster._owner_process_is_alive(os.getpid())

    def refuse(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(pg_testcluster.os, "kill", refuse)
    assert not pg_testcluster._owner_process_is_alive(999999)


def test_owner_owned_by_another_user_counts_as_alive(monkeypatch):
    # Not ours to signal means not ours to reclaim.
    def refuse(pid, sig):
        raise PermissionError

    monkeypatch.setattr(pg_testcluster.os, "kill", refuse)

    assert pg_testcluster._owner_process_is_alive(4242)


def test_prepare_for_pytest_starts_then_sweeps(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pg_testcluster, "ensure_started", lambda: calls.append("start") or 0
    )
    monkeypatch.setattr(
        pg_testcluster,
        "sweep_orphaned_test_databases",
        lambda: calls.append("sweep") or 0,
    )

    assert pg_testcluster.prepare_for_pytest() == 0
    assert calls == ["start", "sweep"]


def test_env_block_exports_cluster_root_and_dsn(monkeypatch):
    root = "/tmp/yoke-pgtest-cluster-custom"
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", root)

    block = pg_testcluster.env_block()

    assert f'export YOKE_PG_CLUSTER_ROOT="{root}"' in block
    assert f'host={root}/sock user=yoketest dbname=postgres' in block


def test_root_without_override_resolves_under_global_scratch_root(
    monkeypatch, tmp_path
):
    """Without YOKE_PG_CLUSTER_ROOT the cluster lives under the shared
    project-agnostic scratch root — ONE location across all execution contexts,
    not a per-context $TMPDIR guess (the source of cross-context divergence)."""
    from yoke_core.domain import project_scratch_dir

    monkeypatch.delenv("YOKE_PG_CLUSTER_ROOT", raising=False)
    monkeypatch.setattr(
        project_scratch_dir, "global_scratch_root", lambda: tmp_path / "scratch"
    )

    assert pg_testcluster._root() == tmp_path / "scratch" / "yoke-pgtest-cluster"
