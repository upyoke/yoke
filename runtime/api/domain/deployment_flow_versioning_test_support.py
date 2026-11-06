# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Any

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain import deployment_runs_schema, schema

from yoke_core.domain.deployment_flow_versioning import (
    cmd_reorder_stages,
    cmd_update_definition,
    cmd_validate_definition,
    cmd_version_definition,
)

from yoke_core.domain.flow_create import cmd_create

from yoke_core.domain.flow_crud import cmd_delete, cmd_set_status, cmd_update_stages

from yoke_core.domain.schema_init import converge_core_schema

from yoke_core.domain.project_seed_test_helpers import (
    SEED_PROJECT_IDS,
    seed_project_identities,
)

ADVANCED_STAGES = json.dumps(
    [
        {
            "name": "preview",
            "step_runner": "ephemeral-deploy",
            "stage_kind": "execution",
            "scope": "run",
            "target": {"kind": "run_preview", "capability": "ephemeral-env"},
        },
        {
            "name": "preview-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "run",
            "target": {"kind": "run_preview", "source_stage": "preview"},
            "verdict": {"mode": "agent_only"},
        },
    ]
)

SUPPORTED_ADVANCED_STAGES = json.dumps(
    [
        {
            "name": "deploy",
            "step_runner": "health-check",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "release-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "run",
            "target": {
                "kind": "persistent_environment",
                "environment": "development",
                "source_stage": "deploy",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
)


def _seed_ephemeral_capability(
    conn: Any, project_id: int = SEED_PROJECT_IDS["yoke"]
) -> None:
    """Register the ``ephemeral-env`` capability an ADVANCED_STAGES preview
    stage names, so ``validate_stage_references`` resolves it like any other
    real project instead of refusing on a fixture gap."""
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (%s, 'ephemeral-env', %s, %s) "
        "ON CONFLICT DO NOTHING",
        (
            project_id,
            '{"trigger":"github-push","preview_domain":"preview.example.com"}',
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()
