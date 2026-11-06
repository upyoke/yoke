# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.deployment_flow_succession import successor_flows

from yoke_core.domain.deployment_item_flow_resolution import (
    FLOW_SOURCE_ITEM,
    item_closing_flows,
    item_completion_flow,
    item_completion_flow_facts,
    lookup_item_project_and_flow,
    membership_closes_item,
)

from yoke_core.domain.deployment_item_completion_runs import completion_runs

from yoke_core.domain.deployment_run_member_admission import admit_run_item

from yoke_core.domain.flow_create import cmd_create

from yoke_core.domain.item_completion_flow_projection import completion_flow_values

_STAGES = json.dumps(
    [{"name": "deploy", "stage_kind": "execution", "step_runner": "auto"}]
)


def _flow(
    conn: Any,
    flow_id: str,
    *,
    status: str = "active",
    supersedes: str | None = None,
    project: str = "yoke",
    created_at: str = "",
) -> None:
    cmd_create(
        conn,
        flow_id,
        project,
        flow_id,
        "",
        _STAGES,
        status=status,
        supersedes_flow_id=supersedes,
    )
    if created_at:
        conn.execute(
            "UPDATE deployment_flows SET created_at = %s WHERE id = %s",
            (created_at, flow_id),
        )
        conn.commit()
