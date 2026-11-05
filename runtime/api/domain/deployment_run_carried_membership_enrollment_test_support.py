# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
    stage_environment,
)

from yoke_core.domain import deployment_run_carried_membership as carried_membership

from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    describe_enrollment,
    enroll_carried_members,
)

from yoke_core.domain.deployment_run_carried_membership_refusal import (
    carried_membership_refusal,
)

from yoke_core.domain.deployment_run_carried_work import derive_carried_work

from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
)

from yoke_core.domain.flow_create import cmd_create

RELEASE_FLOW = "carried-enrollment-flow"

ANCILLARY_FLOW = "carried-enrollment-ancillary-flow"

RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        }
    ]
)


def _flows(conn: Any) -> None:
    stage_environment(conn)
    cmd_create(
        conn,
        RELEASE_FLOW,
        "yoke",
        "Release admission",
        "",
        RELEASE_STAGES,
        status="disabled",
    )
    cmd_create(
        conn,
        ANCILLARY_FLOW,
        "yoke",
        "Ancillary",
        "",
        RELEASE_STAGES,
        takes_delivery_custody=False,
        status="disabled",
    )
