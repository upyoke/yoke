"""Kernel protection through real copy convergence, diagnostics and cleanup."""

from __future__ import annotations

import multiprocessing
from uuid import uuid4

import pytest

from yoke_core.domain import db_backend, migration_fleet_preflight as fleet
from yoke_core.domain import migration_fleet_preflight_transfer as transfer
from yoke_core.domain import migration_rehearsal_copy_lock as admission
from yoke_core.domain import postgres_cluster
from runtime.api.domain.migration_copy_lifetime_support import (
    copy_cluster as _copy_cluster,  # noqa: F401 -- registers copy_cluster
)


HISTORY = ("first", "second")


def _pending(conn, history):
    applied = {
        row[0] for row in conn.execute("SELECT name FROM copy_ledger").fetchall()
    }
    return tuple(name for name in history if name not in applied)


def _converge(conn, _dsn):
    for name in _pending(conn, HISTORY):
        conn.execute("INSERT INTO copy_ledger(name) VALUES (%s)", (name,))


def _real_rehearsal(
    spec,
    database,
    work_dir,
    home,
    diagnostic,
    continue_diagnostic,
    cleanup,
    continue_cleanup,
    results,
):
    admission.machine_config.yoke_home = lambda: home
    real_drop = transfer.drop_copy
    drops = 0

    def drop(cluster, copy_name):
        nonlocal drops
        drops += 1
        if drops == 2:
            cleanup.set()
            assert continue_cleanup.wait(15)
        real_drop(cluster, copy_name)

    def inspect(conn, _dsn):
        assert conn.execute("SELECT count(*) FROM copy_ledger").fetchone()[0] == 2
        diagnostic.set()
        assert continue_diagnostic.wait(15)
        return None

    transfer.drop_copy = drop
    results.put(
        fleet.rehearse(
            postgres_cluster.dsn(spec, database),
            database=database,
            plan=fleet.RehearsalPlan(
                HISTORY, _pending, _converge, post_converge_validator=inspect
            ),
            spec=spec,
            work_dir=work_dir,
            source_environment="disposable-fixture",
        )
    )


def test_real_copy_is_owned_through_diagnostics_and_cleanup(
    tmp_path, monkeypatch, copy_cluster
):
    # The pytest-only socket cluster is disposable. No production connection,
    # source environment resolver or live fleet receipt is involved.
    spec = copy_cluster
    database = "copy_source_" + uuid4().hex
    copy_name = admission.actual_database_name(fleet.REHEARSAL_PREFIX + database)
    home = tmp_path / "home"
    monkeypatch.setattr(admission.machine_config, "yoke_home", lambda: home)
    transfer.create_copy(spec, database)
    conn = db_backend._open_native_postgres(postgres_cluster.dsn(spec, database))
    try:
        conn.execute("CREATE TABLE copy_ledger(name text PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    ctx = multiprocessing.get_context("spawn")
    diagnostic, continue_diagnostic = ctx.Event(), ctx.Event()
    cleanup, continue_cleanup = ctx.Event(), ctx.Event()
    results = ctx.Queue()
    process = ctx.Process(
        target=_real_rehearsal,
        args=(
            spec,
            database,
            tmp_path / "first",
            home,
            diagnostic,
            continue_diagnostic,
            cleanup,
            continue_cleanup,
            results,
        ),
    )
    process.start()
    plan = fleet.RehearsalPlan(HISTORY, _pending, _converge)

    def competing():
        return fleet.rehearse(
            postgres_cluster.dsn(spec, database),
            database=database,
            plan=plan,
            spec=spec,
            work_dir=tmp_path / "second",
            source_environment="disposable-fixture",
        )

    try:
        if not diagnostic.wait(15):
            continue_cleanup.set()
            pytest.fail(
                f"real copy did not reach diagnostics: {results.get(timeout=10)}"
            )
        verdict = competing()
        assert not verdict.passed and "rehearsal_copy_busy" in verdict.detail
        assert not (tmp_path / "second").exists()
        continue_diagnostic.set()
        assert cleanup.wait(15)
        assert "rehearsal_copy_busy" in competing().detail
        # The first copy still exists while cleanup is held; contender cannot drop it.
        conn = db_backend._open_native_postgres(postgres_cluster.dsn(spec, copy_name))
        try:
            assert conn.execute("SELECT count(*) FROM copy_ledger").fetchone()[0] == 2
        finally:
            conn.close()
        continue_cleanup.set()
        verdict = results.get(timeout=15)
        process.join(15)
        assert process.exitcode == 0
        assert (
            verdict.passed
            and verdict.pending_before == HISTORY
            and verdict.applied == HISTORY
        )
        assert not (tmp_path / "first" / f"{database}.dump").exists()
        assert competing().passed
        conn = db_backend._open_native_postgres(postgres_cluster.dsn(spec, database))
        try:
            assert conn.execute("SELECT count(*) FROM copy_ledger").fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        continue_diagnostic.set()
        continue_cleanup.set()
        process.join(15)
        if process.is_alive():
            process.kill()
            process.join()
        transfer.drop_copy(spec, copy_name)
        transfer.drop_copy(spec, database)


@pytest.mark.parametrize(
    "failure", ["dump", "restore", "converge", "diagnostic", "cleanup"]
)
def test_failures_keep_admission_until_the_last_copy_user_stops(
    tmp_path, monkeypatch, failure
):
    spec = postgres_cluster.ClusterSpec(tmp_path / "cluster", "fixture")
    monkeypatch.setattr(
        admission.machine_config, "yoke_home", lambda: tmp_path / "home"
    )
    copy_name = fleet.REHEARSAL_PREFIX + "tenant"
    visited = []

    def operation(name):
        visited.append(name)
        with pytest.raises(admission.RehearsalCopyBusy):
            with admission.copy_lock(spec, copy_name):
                pytest.fail("copy user ran without admission")
        if name == failure:
            raise RuntimeError(f"{name} fixture failure")

    monkeypatch.setattr(fleet, "_live_ownership_verdict", lambda *a: None)
    monkeypatch.setattr(
        fleet.migration_fleet_preflight_extensions, "source_extensions", lambda d: ()
    )
    monkeypatch.setattr(
        fleet.migration_fleet_preflight_extensions, "extension_pins", lambda *a: ()
    )
    monkeypatch.setattr(
        fleet.migration_fleet_preflight_extensions,
        "stage_pinned_extensions",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(transfer, "dump_database", lambda *a, **k: operation("dump"))
    monkeypatch.setattr(transfer, "create_copy", lambda *a: operation("create"))
    monkeypatch.setattr(transfer, "restore_copy", lambda *a, **k: operation("restore"))

    def drop(*args):
        operation("cleanup" if "create" in visited else "initial-drop")

    monkeypatch.setattr(transfer, "drop_copy", drop)

    def converge(*args):
        operation("converge")
        operation("diagnostic")
        return fleet.Verdict("tenant", True, "converged")

    monkeypatch.setattr(fleet, "_converge_copy", converge)
    verdict = fleet.rehearse(
        "fixture-source",
        database="tenant",
        plan=fleet.RehearsalPlan((), lambda *a: (), lambda *a: None),
        spec=spec,
        work_dir=tmp_path / "work",
        source_environment="disposable-fixture",
    )
    assert not verdict.passed and f"{failure} fixture failure" in verdict.detail
    if failure != "dump":
        assert visited[-1] == "cleanup"
    with admission.copy_lock(spec, copy_name):
        pass


def test_busy_kernel_never_probes_source_or_runs_cleanup(tmp_path, monkeypatch):
    spec = postgres_cluster.ClusterSpec(tmp_path / "cluster", "fixture")
    monkeypatch.setattr(
        admission.machine_config, "yoke_home", lambda: tmp_path / "home"
    )

    def forbidden(*args, **kwargs):
        pytest.fail("contending kernel touched source or copy")

    monkeypatch.setattr(fleet, "_live_ownership_verdict", forbidden)
    monkeypatch.setattr(transfer, "drop_copy", forbidden)
    with admission.copy_lock(spec, fleet.REHEARSAL_PREFIX + "tenant"):
        verdict = fleet.rehearse(
            "password=never-print",
            database="tenant",
            plan=fleet.RehearsalPlan((), forbidden, forbidden),
            spec=spec,
            work_dir=tmp_path / "work",
            source_environment="fixture",
        )
    assert "rehearsal_copy_busy" in verdict.detail
    assert not verdict.pending_evaluated
    assert not (tmp_path / "work").exists()
