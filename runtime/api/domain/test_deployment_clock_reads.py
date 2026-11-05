"""Deployment and merge writers read back native timestamp values."""

from runtime.api.domain.deployment_clock_reads_test_support import (
    native_clocks as native_clocks,
)


import json


from runtime.api.domain.deployment_composition_clock_filters_test_support import (
    DRIVER_STAMP,
    clocks as clocks,
)
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import deployment_runs_crud_query
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain import deployment_run_driver_attachment as driver
from yoke_core.domain import merge_queue_landing_marker as marker
from yoke_core.domain import merge_queue_landing_record as records
from yoke_core.domain import merge_queue_landing_refresh as refresh
from yoke_core.domain import deployment_runs_crud_mutate as updates
from yoke_core.domain.qa_latest_execution import select_latest_executions
from yoke_core.domain.qa_run_verdict_record import _clock_columns
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
    deployment_stage_receipt_for_qa,
)

RUN = "run-clock-filter"


def test_superseded_marker_skips_old_clocks_then_same_pr_replays_strictly(
    native_clocks,
):
    native_clocks.execute(
        "UPDATE items SET merge_queue_pr_number='old', merge_queue_enqueued_at='2026-03-09 02:32:26', merge_queue_landed_at='2026-07-30 15:00:27.569899+00', merge_queue_notified_at='2026-07-30 15:00:27+00' WHERE id=1"
    )
    # An operator repoint drops the superseded carrier's clocks; a merge
    # boundary write on this landed item would open a re-land attempt.
    assert (
        marker.repoint_item_at_pull_request(native_clocks, 1, "new")["landed_at"]
        is None
    )
    marker.point_item_at_pull_request(native_clocks, 1, "new", enqueued_at=DRIVER_STAMP)
    assert marker.read_landing_marker(native_clocks, 1)["enqueued_at"] == DRIVER_STAMP
    assert (
        marker.point_item_at_pull_request(native_clocks, 1, "new")["enqueued_at"]
        == DRIVER_STAMP
    )


def test_driver_attach_heartbeat_release_keep_canonical_json(native_clocks):
    args = dict(
        session_id="driver", pid=42, phase=driver.PHASE_EXECUTING, now=DRIVER_STAMP
    )
    driver.attach_driver(native_clocks, RUN, **args)
    repeated = driver.attach_driver(native_clocks, RUN, **args)
    assert repeated.attached_at == DRIVER_STAMP
    assert (
        driver.live_attachment_for_run(
            native_clocks, run_id_value=RUN, now=DRIVER_STAMP
        )
        == repeated
    )
    raw = native_clocks.execute(
        "SELECT driver_attachment FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert json.loads(raw)["heartbeat_at"] == format_instant(DRIVER_STAMP)
    assert driver.release_driver(native_clocks, RUN, session_id="driver", pid=42)


def test_freeze_replay_reads_its_own_stamp(native_clocks, monkeypatch):
    from yoke_core.domain import deployment_run_unheld_candidates as custody
    from yoke_core.domain import deployment_run_carried_membership_refusal as membership
    from yoke_core.domain import deployment_member_run_coverage as coverage

    monkeypatch.setattr(composition, "record_bound_sources", lambda *_: {})
    monkeypatch.setattr(composition, "record_carried_work", lambda *_: {})
    monkeypatch.setattr(custody, "resolve_candidate_custody", lambda *_: None)
    monkeypatch.setattr(membership, "carried_membership_refusal", lambda *_, **__: None)
    monkeypatch.setattr(
        coverage, "unclosable_final_member_refusal", lambda *_, **__: None
    )
    monkeypatch.setattr(composition, "utc_now", lambda: DRIVER_STAMP)
    native_clocks.execute(
        "UPDATE deployment_runs SET composition_frozen_at=NULL WHERE id=%s", (RUN,)
    )
    first = composition.freeze_run_composition(native_clocks, RUN)
    assert first == composition.freeze_run_composition(native_clocks, RUN)
    assert first["frozen_at"] == format_instant(DRIVER_STAMP)


def test_queue_observation_and_refresh_read_their_own_clocks(native_clocks):
    record = records.LandingRecord(
        item_id=1,
        project_id=1,
        pr_number="42",
        state="pending",
        head_sha="a" * 40,
        queue_holding="neither",
        queue_entry_state="absent",
        merge_when_ready="cleared",
        observed_at=DRIVER_STAMP,
        changed_at=DRIVER_STAMP,
    )
    records.write_landing_record(native_clocks, record)
    assert records.read_landing_record(native_clocks, 1).observed_at == DRIVER_STAMP
    assert (
        refresh.record_age_seconds(
            records.read_landing_record(native_clocks, 1).observed_at, now=DRIVER_STAMP
        )
        == 0
    )
    assert refresh.claim_due_projects(native_clocks, [1], now=DRIVER_STAMP) == (1,)
    refresh.complete_projects(native_clocks, [1], now=DRIVER_STAMP)
    assert refresh.read_refresh(native_clocks, 1).completed_at == DRIVER_STAMP
    native_clocks.execute(
        "UPDATE merge_queue_landing_refreshes SET completed_at=NULL WHERE project_id=1"
    )
    assert refresh.read_refresh(native_clocks, 1).completed_at is None
    refresh.fail_projects(native_clocks, [1], now=DRIVER_STAMP, error="fixture")
    assert refresh.read_refresh(native_clocks, 1).started_at == DRIVER_STAMP


def test_qa_attempt_order_uses_its_own_start(native_clocks):
    values = _clock_columns(
        native_clocks,
        dict(
            started_at=DRIVER_STAMP, completed_at=DRIVER_STAMP, created_at=DRIVER_STAMP
        ),
    )
    native_clocks.execute(
        "INSERT INTO qa_runs(id,qa_requirement_id,started_at,completed_at,created_at) VALUES (1,2,%s,%s,%s)",
        tuple(values.values()),
    )
    row = dict(native_clocks.execute("SELECT * FROM qa_runs").fetchone())
    assert select_latest_executions([row])[2]["id"] == 1
    assert all(parse_instant(row[name]) == DRIVER_STAMP for name in values)


def test_receipt_attempts_and_retry_reads_preserve_identity(native_clocks):
    native_clocks.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id='successor'",
        (
            json.dumps(
                [dict(name="deploy", stage_kind="execution", step_runner="auto")]
            ),
        ),
    )
    native_clocks.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='deploy' WHERE id=%s",
        (RUN,),
    )
    params = dict(
        run_id=RUN,
        stage_name="deploy",
        correlation_id="attempt",
        target_kind="persistent_environment",
        executor="fixture",
    )
    receipt = allocate_deployment_stage_receipt(native_clocks, **params)
    assert (
        allocate_deployment_stage_receipt(native_clocks, **params)["id"]
        == receipt["id"]
    )
    completed = complete_deployment_stage_receipt(
        native_clocks,
        run_id=RUN,
        receipt_id=receipt["id"],
        correlation_id="attempt",
        status="ready",
        target_name="prod",
        observed_release_lineage="a" * 40,
    )
    assert parse_instant(completed["completed_at"]) == completed["completed_at"]
    assert (
        deployment_stage_receipt_for_qa(
            native_clocks,
            run_id=RUN,
            source_stage="deploy",
            expected_target_kind="persistent_environment",
            expected_target_name="prod",
            expected_release_lineage="a" * 40,
        )["id"]
        == receipt["id"]
    )
    for field, expected in (
        ("status", "executing"),
        ("release_lineage", "a" * 40),
        ("flow", "successor"),
    ):
        assert deployment_runs_crud_query.cmd_get(RUN, field) == expected


def test_run_updates_and_retry_projection_leave_unused_clocks_opaque(native_clocks):
    native_clocks.execute(
        "UPDATE deployment_runs SET carried_work='{}' WHERE id=%s", (RUN,)
    )
    assert updates.cmd_update(RUN, "current_stage", "deploy") is None
    entered = native_clocks.execute(
        "SELECT current_stage_entered_at FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert not isinstance(entered, str)
    assert parse_instant(entered) == entered
    assert updates.cmd_update(RUN, "current_stage", "deploy") is None
    assert (
        native_clocks.execute(
            "SELECT current_stage_entered_at FROM deployment_runs WHERE id=%s", (RUN,)
        ).fetchone()[0]
        == entered
    )
    assert updates.cmd_update(RUN, "current_stage", "qa") is None
    native = native_clocks.execute(
        "SELECT current_stage_entered_at FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert parse_instant(native) == native
    assert not isinstance(native, str)
    assert updates.cmd_update(RUN, "status", "failed") is None
    assert deployment_runs_crud_query.cmd_get(RUN, "status") == "failed"
    assert "failed" in deployment_runs_crud_query.cmd_get(RUN)
