# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from unittest import mock

from runtime.api.domain.deployment_qa_stage_dispatch_wake_test_support import (
    _WAITING,
    _member,
    _run,
)

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)

from runtime.api.steering_fleet_test_helpers import (
    WORKER_SESSION,
    compose,
    seed_steering_scope,
)

from yoke_core.domain import deployment_qa_dispatch_wait_notice as wait_notice_mod

from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_qa_manual_wake import (
    NO_OWNER,
    manual_wake_requirements,
)

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain.steering_fleet_report_projection import report_dict

from yoke_core.domain.steering_fleet_report_render import report_body

from yoke_core.domain.work_claim_targets import make_item_target

EVIDENCE = "a deployment run with at least 44 members exists after this release"


def _requirement(
    conn: Any,
    *,
    requirement_id: int,
    run_id: str,
    member: int,
    wake_path: str | None,
    stage: str = "item-qa",
) -> None:
    conn.execute(
        "INSERT INTO qa_requirements(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,qa_kind,qa_phase,blocking_mode,"
        "requirement_source,method_id,plan_case_key,wake_path,wake_evidence,"
        "created_at) VALUES (%s,%s,%s,%s,'plan_case','post_deploy','blocking',"
        "'flow_derived','exploratory-mission','real-traffic',%s,%s,%s)",
        (
            requirement_id,
            run_id,
            stage,
            member,
            wake_path,
            EVIDENCE if wake_path == "manual" else None,
            iso8601_now(),
        ),
    )
    conn.commit()
