# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)

from runtime.api.fixtures.qa_declared_replacement_fixture import (
    corrected_case,
    declare,
    requirement_row,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.qa_deployment_case_content_refresh import (
    declare_refreshed_replacements,
)

from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)

from yoke_core.domain.qa_requirement_replacement import (
    QaReplacementError,
    declare_existing_replacement,
)

from yoke_core.domain.qa_run_verdict_record import insert_qa_run

MEMBER = 9811


def _status(conn: Any, run_id: str) -> dict[str, Any]:
    return deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=MEMBER
    )


def _failed_with_correction(
    conn: Any, run_id: str, verdict: str = "fail"
) -> tuple[int, int]:
    failed_id = seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)
    record_case_verdict(conn, failed_id, verdict, evidence=True)
    corrected_id = corrected_case(conn, failed_id=failed_id, case_key="smoke-fixed")
    declare(conn, failed_id, "smoke-fixed", [corrected_id])
    return failed_id, corrected_id
