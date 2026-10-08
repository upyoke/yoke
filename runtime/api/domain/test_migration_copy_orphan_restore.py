"""A real pg_restore must retain admission after its Python driver is killed."""

from __future__ import annotations

import multiprocessing
from uuid import uuid4

from yoke_core.domain import db_backend, postgres_cluster
from yoke_core.domain import migration_fleet_preflight as fleet
from yoke_core.domain import migration_fleet_preflight_transfer as transfer
from yoke_core.domain import migration_rehearsal_copy_lock as admission
from runtime.api.domain.migration_copy_lifetime_support import (
    copy_cluster as _copy_cluster,  # noqa: F401 -- registers copy_cluster
    wait_until,
)


BARRIER_KEY = 761324


def _pending(conn, history):
    return (
        tuple(history)
        if conn.execute("SELECT count(*) FROM payload").fetchone()[0]
        else ()
    )


def _converge(conn, _dsn):
    conn.execute("DELETE FROM payload")


def _rehearse(spec, database, home, work_dir):
    admission.machine_config.yoke_home = lambda: home
    return fleet.rehearse(
        postgres_cluster.dsn(spec, database),
        database=database,
        plan=fleet.RehearsalPlan(("empty_payload",), _pending, _converge),
        spec=spec,
        work_dir=work_dir,
        source_environment="disposable-fixture",
    )


def _driver(spec, database, home, work_dir, before_restore, allow_restore, results):
    real_restore = transfer.restore_copy

    def synchronized_restore(*args, **kwargs):
        # Only synchronize entry. The real pg_restore, dump, kernel and lock run.
        before_restore.set()
        assert allow_restore.wait(15)
        return real_restore(*args, **kwargs)

    transfer.restore_copy = synchronized_restore
    results.put(_rehearse(spec, database, home, work_dir))


def _available(spec, copy_name):
    try:
        with admission.copy_lock(spec, copy_name):
            return True
    except admission.RehearsalCopyBusy:
        return False


def test_killed_driver_cannot_expose_a_copy_still_used_by_pg_restore(
    tmp_path, monkeypatch, copy_cluster
):
    spec = copy_cluster
    database = "orphan_source_" + uuid4().hex
    copy_name = admission.actual_database_name(fleet.REHEARSAL_PREFIX + database)
    home = tmp_path / "home"
    monkeypatch.setattr(admission.machine_config, "yoke_home", lambda: home)
    transfer.create_copy(spec, database)
    with db_backend.connect_psycopg(postgres_cluster.dsn(spec, database)) as conn:
        # During restore, CREATE INDEX waits on a lock held by the test. This
        # establishes a live database-using *Postgres client*, not a fake child.
        conn.execute(
            "CREATE FUNCTION restore_barrier(value integer) RETURNS integer "
            "LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN "
            f"PERFORM pg_advisory_xact_lock({BARRIER_KEY}); RETURN value; END $$"
        )
        conn.execute("CREATE TABLE payload(value integer)")
        conn.execute("INSERT INTO payload VALUES (1)")
        conn.execute("CREATE INDEX payload_value ON payload(restore_barrier(value))")
    ctx = multiprocessing.get_context("spawn")
    before_restore, allow_restore = ctx.Event(), ctx.Event()
    results = ctx.Queue()
    driver = ctx.Process(
        target=_driver,
        args=(
            spec,
            database,
            home,
            tmp_path / "holder",
            before_restore,
            allow_restore,
            results,
        ),
    )
    blocker = None
    driver.start()
    try:
        if not before_restore.wait(15):
            raise AssertionError(
                f"rehearsal never reached restore: {results.get(timeout=5)}"
            )
        blocker = db_backend.connect_psycopg(postgres_cluster.dsn(spec, copy_name))
        blocker.autocommit = True
        blocker.execute("SELECT pg_advisory_lock(%s)", (BARRIER_KEY,))
        copy_oid = blocker.execute(
            "SELECT oid FROM pg_database WHERE datname = %s", (copy_name,)
        ).fetchone()[0]

        def restoring():
            return blocker.execute(
                "SELECT pid FROM pg_stat_activity WHERE datname = %s "
                "AND application_name = 'pg_restore' AND wait_event = 'advisory'",
                (copy_name,),
            ).fetchone()

        allow_restore.set()
        wait_until(restoring)
        driver.kill()
        driver.join(10)
        assert driver.exitcode is not None and driver.exitcode < 0
        assert restoring(), "pg_restore must remain alive after driver death"
        verdict = _rehearse(spec, database, home, tmp_path / "contender")
        assert not verdict.passed and "rehearsal_copy_busy" in verdict.detail
        assert not (tmp_path / "contender").exists()
        assert (
            blocker.execute(
                "SELECT oid FROM pg_database WHERE datname = %s", (copy_name,)
            ).fetchone()[0]
            == copy_oid
        )
        assert blocker.execute("SELECT count(*) FROM payload").fetchone()[0] == 1
        blocker.execute("SELECT pg_advisory_unlock(%s)", (BARRIER_KEY,))
        wait_until(lambda: _available(spec, copy_name))
        assert blocker.execute("SELECT to_regclass('payload_value')").fetchone()[0]
        blocker.close()
        blocker = None
        # The orphan's completed copy may now be dropped and recreated safely.
        verdict = _rehearse(spec, database, home, tmp_path / "contender")
        assert verdict.passed and verdict.applied == ("empty_payload",)
        with db_backend.connect_psycopg(postgres_cluster.dsn(spec, database)) as conn:
            assert conn.execute("SELECT count(*) FROM payload").fetchone()[0] == 1
    finally:
        allow_restore.set()
        if blocker is not None:
            blocker.close()
        if driver.is_alive():
            driver.kill()
        driver.join(10)
        wait_until(lambda: _available(spec, copy_name))
        transfer.drop_copy(spec, copy_name)
        transfer.drop_copy(spec, database)
