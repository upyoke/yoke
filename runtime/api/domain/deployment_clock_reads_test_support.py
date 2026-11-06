# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from types import SimpleNamespace

import pytest

from runtime.api.domain.deployment_composition_clock_filters_test_support import (
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


@pytest.fixture
def native_clocks(clocks, monkeypatch):
    clocks.execute("CREATE TABLE environments (id integer PRIMARY KEY, name text)")
    clocks.execute(
        "ALTER TABLE deployment_runs ADD target_tier text, "
        "ADD target_environment_id integer, ADD created_by text, "
        "ADD supersedes_run_id text, ADD superseded_by_run_id text"
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
        "CREATE TABLE qa_requirements (id integer,item_id integer,qa_kind text,deployment_run_id text,method_id integer,waived_at text,execution_target_digest text,execution_target_json text,deployment_member_item_id integer,plan_case_key text,"
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
        "CREATE TABLE merge_queue_landing_attempts (item_id integer,project_id integer,pr_number text,enqueued_at timestamptz,opened_at timestamptz,closed_at timestamptz,closed_reason text NOT NULL DEFAULT '',PRIMARY KEY(item_id,pr_number))"
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
    from yoke_core.domain.merge_queue_landing_record_schema import (
        ensure_merge_queue_landing_record_schema,
    )

    ensure_merge_queue_landing_record_schema(clocks)
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
    from runtime.api.workflow_pin_test_support import install_workflow_pin

    install_workflow_pin(clocks)
    yield clocks
