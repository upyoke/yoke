# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    seed_run_standing_on_qa_stage,
)

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.deployment_qa_plan_groups import run_groups

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_prerequisites import (
    prior_stage_refusals,
    require_prior_stage_acceptance,
)

from yoke_core.domain.post_deploy_verification_answer import NO_OBLIGATION_QA_KIND

PREVIEW_QA = "preview-item-qa"

LINEAGE = "d" * 40


def _preview_producer(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "step_runner": "ephemeral-deploy",
        "stage_kind": "execution",
        "scope": "run",
        "target": {"kind": "run_preview", "capability": "ephemeral-env"},
    }


def _item_qa(
    name: str, *, source_stage: str, kind: str, environment: str = "stage"
) -> dict[str, Any]:
    target: dict[str, Any] = {"kind": kind, "source_stage": source_stage}
    if kind == "persistent_environment":
        target["environment"] = environment
    return {
        "name": name,
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
        "target": target,
        "verdict": {"mode": "agent_only"},
    }


def _preview_qa_stages() -> list[dict[str, Any]]:
    return [
        _preview_producer("release-preview"),
        _item_qa(PREVIEW_QA, source_stage="release-preview", kind="run_preview"),
    ]


def _seed_ephemeral_capability(conn: Any) -> None:
    from yoke_core.domain.project_identity import resolve_project_id

    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (%s, 'ephemeral-env', %s, %s) ON CONFLICT DO NOTHING",
        (
            resolve_project_id(conn, "yoke"),
            '{"trigger":"github-push","preview_domain":"preview.example.com"}',
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()


def _environment_id(conn: Any, name: str = "stage") -> int:
    row = conn.execute(
        "SELECT e.id FROM environments e WHERE e.project_id=1 AND e.name=%s",
        (name,),
    ).fetchone()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _bind_plan(conn: Any, *, slug: str, environment_id: int) -> int:
    plan_id = create_smoke_plan(conn, project="yoke", slug=slug)
    conn.execute(
        "UPDATE qa_plans SET target_environment_id=%s WHERE id=%s",
        (int(environment_id), int(plan_id)),
    )
    conn.commit()
    return int(plan_id)


def _point_run_at_environment(conn: Any, run_id: str, environment_id: int) -> None:
    conn.execute(
        "UPDATE deployment_runs SET target_tier='persistent', "
        "target_environment_id=%s WHERE id=%s",
        (int(environment_id), run_id),
    )
    conn.commit()
