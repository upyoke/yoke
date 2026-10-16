"""Deployment and merge writers read back native timestamp values."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_deployment_composition_clock_filters import (
    DRIVER_STAMP,
    clocks as clocks,
    history,
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
    DEPLOYMENT_STAGE_RECEIPTS_SQL,
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
    deployment_stage_receipt_for_qa,
)

RUN = "run-clock-filter"


@pytest.fixture
def native_clocks(clocks, monkeypatch):
    clocks.execute("CREATE TABLE environments (id integer PRIMARY KEY, name text)")
    clocks.execute(
        "ALTER TABLE deployment_runs ADD target_tier text, "
        "ADD target_environment_id integer, ADD created_by text"
    )
    clocks.execute(
        "ALTER TABLE items ADD merge_queue_pr_number text, ADD merge_queue_enqueued_at text, ADD merge_queue_notified_at text"
    )
    clocks.execute(
        "ALTER TABLE deployment_flows ADD takes_delivery_custody boolean DEFAULT true, ADD stages text DEFAULT '[]'"
    )
    clocks.execute(
        "ALTER TABLE deployment_runs ADD driver_attachment text, ADD composition_frozen_at text, ADD requirement_snapshot text, ADD current_stage text, ADD current_stage_entered_at text, ADD started_at text, ADD completed_at text, ADD carried_work text, ADD bound_sources text, ADD artifact_identity text, ADD composition_resolution text"
    )
    clocks.execute(
        "CREATE TABLE deployment_run_items (run_id text,item_id integer,delivery_intent text,requirement_selection text,requirement_snapshot text)"
    )
    clocks.execute(
        "CREATE TABLE qa_requirements (id integer,item_id integer,qa_kind text,deployment_run_id text,method_id integer,waived_at text,execution_target_digest text,plan_case_key text,"
        "superseded_by_requirement_id integer,replacement_requirement_id integer,retracted_at text,retraction_rationale text,retraction_source text,"
        "waiver_rationale text,waiver_source text,superseded_at text,supersession_rationale text,supersession_source text)"
    )
    clocks.execute(
        "CREATE TABLE qa_runs (id integer,qa_requirement_id integer,started_at text,completed_at text,created_at text,verdict text,case_outcome text,raw_result text)"
    )
    clocks.execute(
        "CREATE TABLE qa_plan_review_verdicts (capture_run_id integer,review_run_id integer,requirement_id integer)"
    )
    clocks.execute(
        "CREATE TABLE item_status_transitions (item_id integer,task_num integer,to_status text,created_at text)"
    )
    clocks.execute(
        "CREATE TABLE merge_queue_landing_refreshes (project_id integer PRIMARY KEY,started_at text,completed_at text,last_error text)"
    )
    clocks.execute(
        "CREATE TABLE merge_queue_landing_records (item_id integer PRIMARY KEY,project_id integer,pr_number text,state text,head_sha text,queue_holding text,queue_entry_state text,merge_when_ready text,failed_checks text,narrative text,disarm_note text,observed_at text,changed_at text)"
    )
    clocks.execute(
        "CREATE TABLE item_sections (item_id integer NOT NULL,section_name text NOT NULL,"
        "content text,ordering integer,source text NOT NULL DEFAULT 'operator',"
        "created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,"
        "PRIMARY KEY(item_id,section_name))"
    )
    clocks.execute(DEPLOYMENT_STAGE_RECEIPTS_SQL.replace("TIMESTAMPTZ", "TEXT"))
    proxy = SimpleNamespace(
        execute=clocks.execute,
        commit=clocks.commit,
        rollback=clocks.rollback,
        close=lambda: None,
        info=clocks.info,
    )
    monkeypatch.setattr(deployment_runs_crud_query, "connect", lambda *_: proxy)
    monkeypatch.setattr(updates, "connect", lambda *_: proxy)
    history.apply(clocks)
    history.invariants(clocks)
    yield clocks


def test_superseded_marker_skips_old_clocks_then_same_pr_replays_strictly(
    native_clocks,
):
    native_clocks.execute(
        "UPDATE items SET merge_queue_pr_number='old', merge_queue_enqueued_at='2026-03-09 02:32:26', merge_queue_landed_at='2026-07-30 15:00:27.569899+00', merge_queue_notified_at='2026-07-30 15:00:27+00' WHERE id=1"
    )
    assert (
        marker.point_item_at_pull_request(native_clocks, 1, "new")["landed_at"] is None
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
