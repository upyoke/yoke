"""Tests for when and how the orphan sweep runs.

Its sibling covers WHAT a sweep may reclaim; these cover the scheduling
properties that keep cleanup from becoming the stall it exists to prevent:
it runs detached, one at a time, and within a time budget.
"""

from __future__ import annotations

import os
import subprocess

from yoke_core.domain import pg_test_db_namespace
from yoke_core.domain.db_backend import POSTGRES_TEST_DB_PREFIX
from yoke_core.tools import pg_testcluster, pg_testcluster_orphans


def _completed(stdout: str = '', returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr='')


def _name_owned_by(pid: int, purpose: str = 'abc') -> str:
    return (
        f"{POSTGRES_TEST_DB_PREFIX}"
        f"{pg_test_db_namespace.mint_run_tag(pid=pid)}_{purpose}"
    )


def test_prepare_for_pytest_starts_then_detaches_the_sweep(monkeypatch):
    """Cleanup must never sit in a suite's critical path.

    Dropping a database is seconds of disk work on a loaded machine, so a
    synchronous sweep of a large backlog delays pytest collection by minutes —
    observed live as gates that could not start at all. Startup kicks the sweep
    off and moves on.
    """
    calls = []
    monkeypatch.setattr(
        pg_testcluster, "ensure_started", lambda: calls.append("start") or 0
    )
    monkeypatch.setattr(
        pg_testcluster,
        "start_detached_orphan_sweep",
        lambda: calls.append("detached-sweep"),
    )
    monkeypatch.setattr(
        pg_testcluster,
        "sweep_orphaned_test_databases",
        lambda: calls.append("blocking-sweep") or 0,
    )

    assert pg_testcluster.prepare_for_pytest() == 0
    assert calls == ["start", "detached-sweep"]


def test_prepare_for_pytest_stops_when_the_cluster_will_not_start(monkeypatch):
    calls = []
    monkeypatch.setattr(pg_testcluster, "ensure_started", lambda: 1)
    monkeypatch.setattr(
        pg_testcluster,
        "start_detached_orphan_sweep",
        lambda: calls.append("detached-sweep"),
    )

    assert pg_testcluster.prepare_for_pytest() == 1
    assert calls == []


def test_detached_sweep_outlives_its_launcher(monkeypatch):
    spawned = {}

    def fake_popen(argv, **kwargs):
        spawned["argv"] = argv
        spawned["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(pg_testcluster_orphans.subprocess, "Popen", fake_popen)

    pg_testcluster_orphans.start_detached_orphan_sweep()

    assert spawned["argv"][1:] == [
        "-m", "yoke_core.tools.pg_testcluster", "prune",
    ]
    # A new session keeps the sweep alive past the run that started it, and
    # detached streams keep it from holding the launcher's pipes open.
    assert spawned["kwargs"]["start_new_session"] is True


def test_detached_sweep_never_fails_the_run(monkeypatch):
    def refuse(argv, **kwargs):
        raise OSError("cannot fork")

    monkeypatch.setattr(pg_testcluster_orphans.subprocess, "Popen", refuse)

    pg_testcluster_orphans.start_detached_orphan_sweep()  # must not raise


def test_only_one_sweeper_runs_at_a_time(monkeypatch, tmp_path):
    """Concurrent sweeps are worse than none.

    Every invocation would target the same backlog and spend its time
    colliding on the same DROP locks instead of reclaiming anything.
    """
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", str(tmp_path / "cluster"))
    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    reclaimed = []
    monkeypatch.setattr(
        pg_testcluster_orphans,
        "_reclaim_orphans",
        lambda: reclaimed.append(1) or 0,
    )

    with pg_testcluster_orphans._single_sweeper() as first_holder:
        assert first_holder is True
        # A second sweeper, holding no lock, must decline instantly.
        assert pg_testcluster_orphans.sweep_orphaned_test_databases() == 0
        assert reclaimed == []

    assert pg_testcluster_orphans.sweep_orphaned_test_databases() == 0
    assert reclaimed == [1]


def test_sweep_stops_at_its_time_budget_and_says_what_is_left(
    monkeypatch, capsys
):
    # A backlog must drain over several runs rather than one process grinding
    # through hundreds of databases while everything else waits.
    names = [_name_owned_by(9000 + i) for i in range(4)]
    clock = iter([0.0, 0.0, 1.0, 999.0, 999.0, 999.0, 999.0])

    def fake_psql(sql: str, *, statement_timeout_ms=None):
        if sql.startswith("SELECT"):
            return _completed("\n".join(names) + "\n")
        return _completed()

    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_psql", fake_psql)
    monkeypatch.setattr(
        pg_testcluster_orphans, "_owner_process_is_alive", lambda pid: False
    )
    monkeypatch.setattr(pg_testcluster_orphans.time, "monotonic", lambda: next(clock))

    pg_testcluster_orphans._reclaim_orphans()

    err = capsys.readouterr().err
    assert "left for the next sweep" in err



def test_detached_sweep_command_is_actually_runnable(tmp_path, monkeypatch):
    """Run the spawned command for real, rather than trusting its argv.

    The sweep's output is discarded, so a command line that cannot start —
    a module with no entry point, say — fails silently and cleanup simply
    never happens. Only executing it proves the target exists. Pointed at an
    empty cluster root there is nothing running to sweep, so it should report
    success without touching anything.
    """
    spawned = {}

    def capture(argv, **kwargs):
        spawned["argv"] = argv
        return object()

    monkeypatch.setattr(pg_testcluster_orphans.subprocess, "Popen", capture)
    pg_testcluster_orphans.start_detached_orphan_sweep()
    # `subprocess` is one shared module object, so the patch above would
    # also intercept this test's own run() call. Drop it before executing.
    monkeypatch.undo()

    env = dict(os.environ, YOKE_PG_CLUSTER_ROOT=str(tmp_path / "empty-cluster"))
    completed = subprocess.run(
        spawned["argv"], capture_output=True, text=True, env=env, timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert "No module named" not in completed.stderr
