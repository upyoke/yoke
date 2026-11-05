# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

from runtime.api.fixtures.completed_delivery import (
    _stage as _stage,
    seed_selected_requirement_run as _seed_selected_requirement_run,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)

from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements


def _original_requirement(conn: Any, *, item_id: int, method_id: str | None) -> int:
    columns = [
        "item_id",
        "qa_kind",
        "qa_phase",
        "target_env",
        "blocking_mode",
        "requirement_source",
        "instructions",
        "expected_outcome",
        "created_at",
    ]
    values: list[Any] = [
        item_id,
        "visual_acceptance",
        "post_deploy",
        "stage",
        "blocking",
        "explicit",
        "Capture the deployed release summary before accepting it.",
        "The release summary shows the admitted item and running revision.",
        "2026-09-14T00:00:00Z",
    ]
    if method_id is not None:
        method = conn.execute(
            "SELECT name,runner_id,required_capability_kinds,verdict_path "
            "FROM qa_methods WHERE id=%s",
            (method_id,),
        ).fetchone()
        columns.extend(
            [
                "method_id",
                "method_name",
                "runner_id",
                "capability_requirements",
                "verdict_path",
                "method_config",
            ]
        )
        values.extend(
            [
                method_id,
                method["name"],
                method["runner_id"],
                method["required_capability_kinds"],
                method["verdict_path"],
                json.dumps(
                    {
                        "steps": [
                            {"action": "navigate", "route": "/releases/current"},
                            {"action": "screenshot", "capture": True},
                        ]
                    }
                ),
            ]
        )
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) VALUES "
        f"({','.join('%s' for _ in columns)}) RETURNING id",
        tuple(values),
    ).fetchone()
    conn.commit()
    return int(row["id"])
