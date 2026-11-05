# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run

import json

import time

from typing import Any

from runtime.api.steering_fleet_test_helpers import (
    NOW,
    PROJECT_ID,
    compose,
    seed_steering_scope,
)

from yoke_core.domain.steering_fleet_report_run_progress import run_progress

from yoke_core.domain.steering_fleet_report_projection import report_dict

from yoke_core.domain.steering_fleet_report_render import report_body

STARTED = "2026-08-26T08:00:00.000000Z"

STAGE_QA = "item-qa"

STAGE_RELEASE = "hosted-release"


def _seed_run(
    conn,
    *,
    run_id: str,
    stage: str = STAGE_QA,
    status: str = "executing",
    receipt_at: str | None = STARTED,
    started_at: str = STARTED,
    entered_at: str | None = STARTED,
) -> None:
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=1,
        flow="prod-release",
        status=status,
        current_stage=stage,
        created_at=started_at,
        started_at=started_at,
        current_stage_entered_at=entered_at,
    )
    if receipt_at is None:
        return
    conn.execute(
        "INSERT INTO deployment_stage_receipts"
        "(run_id,stage_name,attempt_number,correlation_id,target_kind,"
        "target_name,status,executor,created_at) "
        "VALUES (%s,%s,1,%s,'persistent_environment','prod','pending','operator',%s)",
        (run_id, stage, f"{run_id}:{stage}:1", receipt_at),
    )


def _seed_requirement(
    conn,
    *,
    run_id: str,
    requirement_id: int,
    member_item_id: int | None,
    waived_at: str | None = None,
    superseded_by: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO qa_requirements"
        "(id,deployment_run_id,deployment_stage,deployment_member_item_id,"
        "qa_kind,qa_phase,blocking_mode,requirement_source,created_at,"
        "waived_at,superseded_by_requirement_id) "
        "VALUES (%s,%s,%s,%s,'browser','post_deploy','blocking','flow_derived',"
        "%s,%s,%s)",
        (
            requirement_id,
            run_id,
            STAGE_QA,
            member_item_id,
            STARTED,
            waived_at,
            superseded_by,
        ),
    )


def _record_verdict(
    conn, *, requirement_id: int, verdict: str, at: str = STARTED
) -> None:
    conn.execute(
        "INSERT INTO qa_runs"
        "(qa_requirement_id,performed_by,qa_kind,verdict,started_at,created_at,completed_at) "
        "VALUES (%s,'agent','browser',%s,%s,%s,%s)",
        (requirement_id, verdict, at, at, at),
    )
