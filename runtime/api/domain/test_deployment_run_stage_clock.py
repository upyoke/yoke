"""Stage changes stamp an atomic clock; re-entry never resets stage age."""

from datetime import timedelta

import pytest
from yoke_contracts.timestamps import parse_instant

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.domain.test_steering_fleet_report_deployment_run_facts import _seed_run
from runtime.api.domain.test_deployment_run_member_removal import (
    ITEM,
    RUN,
    REASON,
    _red_member,
)
from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
from yoke_core.domain import deployment_run_stage_entry as clock
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update, cmd_remove_item
from yoke_core.domain.flow_init import converge_flow_catalog

ENTERED = parse_instant("2026-08-26T11:59:00Z")
LATER = parse_instant("2026-08-26T12:05:00Z")


def _row(conn, run_id):
    return conn.execute(
        "SELECT current_stage,current_stage_entered_at FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()


def test_stage_update_stamps_entry_and_repeated_update_preserves_it(
    test_db, monkeypatch
):
    conn = seed_steering_scope(test_db)
    run_id = "run-stamped-stage"
    _seed_run(conn, run_id=run_id, entered_at=None)
    conn.commit()
    monkeypatch.setattr(clock, "utc_now", lambda: ENTERED)

    assert cmd_update(run_id, "current_stage", "complete") is None
    row = _row(conn, run_id)
    assert row["current_stage"] == "complete"
    assert row["current_stage_entered_at"] == ENTERED

    monkeypatch.setattr(clock, "utc_now", lambda: LATER)
    assert cmd_update(run_id, "current_stage", "complete") is None
    assert _row(conn, run_id)["current_stage_entered_at"] == ENTERED
    assert cmd_update(run_id, "current_stage", "repair") is None
    assert _row(conn, run_id)["current_stage_entered_at"] == LATER


def test_automatic_completion_stamps_complete(test_db, monkeypatch):
    _red_member(test_db)
    release_seeded_driver(test_db, RUN)
    monkeypatch.setattr(clock, "utc_now", lambda: ENTERED)

    cmd_remove_item(RUN, ITEM, reason=REASON)

    row = _row(test_db, RUN)
    assert row["current_stage"] == "complete"
    assert row["current_stage_entered_at"] == ENTERED


def test_boot_adds_column_without_backfilling_existing_runs(test_db):
    conn = seed_steering_scope(test_db)
    run_id = "run-before-convergence"
    _seed_run(conn, run_id=run_id, entered_at=None)
    conn.execute("ALTER TABLE deployment_runs DROP COLUMN current_stage_entered_at")
    conn.commit()
    clock.set_current_stage(conn, run_id, "complete")
    conn.commit()

    converge_flow_catalog(conn)
    converge_flow_catalog(conn)

    row = _row(conn, run_id)
    assert row["current_stage"] == "complete"
    assert row["current_stage_entered_at"] is None


def test_execution_guard_does_not_reopen_a_terminal_stage_clock(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    run_id = "run-terminal-stage"
    _seed_run(conn, run_id=run_id, status="succeeded", entered_at=ENTERED)
    conn.commit()
    monkeypatch.setattr(clock, "utc_now", lambda: LATER)

    clock.set_current_stage(conn, run_id, "complete", only_executing=True)
    conn.commit()

    row = _row(conn, run_id)
    assert row["current_stage"] == "item-qa"
    assert row["current_stage_entered_at"] == ENTERED


def test_complete_ages_from_its_clock_without_a_receipt(test_db):
    conn = seed_steering_scope(test_db)
    _seed_run(
        conn,
        run_id="run-wrap-up",
        stage="complete",
        entered_at=ENTERED,
        receipt_at=None,
    )
    conn.commit()

    run = compose(conn).deployment_runs[0]
    assert run.stage == "complete"
    assert run.stage_seconds == 60


def test_complete_with_no_entry_clock_has_unknown_age(test_db):
    conn = seed_steering_scope(test_db)
    _seed_run(conn, run_id="run-old-wrap-up", stage="complete", entered_at=None)
    conn.commit()

    assert compose(conn).deployment_runs[0].stage_seconds is None


def test_snapshot_stage_repair_does_not_keep_the_previous_stage_age(test_db):
    from runtime.api.domain.test_deployment_run_projection import (
        _flow,
        _snapshot,
        RUN_ID,
    )
    from yoke_core.domain.deployment_run_projection import (
        project_snapshot,
        snapshot_digest,
    )

    _flow(test_db)
    before = _snapshot(current_stage="warm-up")
    project_snapshot(before, conn=test_db)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage_entered_at=%s WHERE id=%s",
        (ENTERED, RUN_ID),
    )
    test_db.commit()

    project_snapshot(
        _snapshot(), expected_destination_digest=snapshot_digest(before), conn=test_db
    )

    row = _row(test_db, RUN_ID)
    assert row["current_stage"] == "complete"
    assert row["current_stage_entered_at"] is None


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_stage_entry_keeps_microseconds_and_only_changes_with_the_stage(
    test_db, monkeypatch, zone
):
    conn = seed_steering_scope(test_db)
    conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    run_id = "run-native-stage"
    _seed_run(conn, run_id=run_id, entered_at=None)
    stamp = parse_instant("1969-12-31T23:59:59.999999Z")
    monkeypatch.setattr(clock, "utc_now", lambda: stamp)
    clock.set_current_stage(conn, run_id, "complete")
    assert _row(conn, run_id)["current_stage_entered_at"] == stamp
    stamp += timedelta(microseconds=1)
    clock.set_current_stage(conn, run_id, "complete")
    assert _row(conn, run_id)["current_stage_entered_at"] == stamp - timedelta(
        microseconds=1
    )
    clock.set_current_stage(conn, run_id, "repair")
    assert _row(conn, run_id)["current_stage_entered_at"] == stamp
