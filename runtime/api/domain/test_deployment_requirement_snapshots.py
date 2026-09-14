"""Release admission selects QA requirements within item and run ownership."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.flow_create import cmd_create


def _flow(conn: Any) -> None:
    stages = json.dumps(
        [
            {
                "name": "deploy",
                "step_runner": "auto",
                "stage_kind": "execution",
                "scope": "run",
            },
            {
                "name": "item-qa",
                "step_runner": "qa",
                "stage_kind": "qa",
                "scope": "item",
                "target": {
                    "kind": "persistent_environment",
                    "environment": "stage",
                    "source_stage": "deploy",
                },
                "verdict": {"mode": "agent_only"},
            }
        ]
    )
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,1,'stage','2026-09-14T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    conn.commit()
    cmd_create(
        conn,
        "advanced-requirements",
        "yoke",
        "Advanced requirements",
        "",
        stages,
        status="disabled",
    )


def _run(conn: Any, run_id: str, lineage: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at,composition_resolution) VALUES "
        "(%s,1,'advanced-requirements',%s,'created',%s,'baseline attested')",
        (run_id, lineage, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


def test_explicit_requirement_selection_rejects_foreign_item_and_run(
    test_db: Any,
) -> None:
    _flow(test_db)
    for item_id in (9421, 9422):
        insert_item(
            test_db,
            id=item_id,
            project_sequence=item_id - 9000,
            workflow_id="blitz",
            status="implementing",
            deployment_flow="advanced-requirements",
        )
    _run(test_db, "run-selection", "e" * 40)
    _run(test_db, "run-foreign", "f" * 40)
    foreign_item = insert_qa_requirement(test_db, item_id=9422)
    foreign_run = insert_qa_requirement(
        test_db, item_id=None, deployment_run_id="run-foreign"
    )

    with pytest.raises(ValueError, match="not owned by item 9421"):
        cmd_add_item("run-selection", 9421, requirement_ids=[foreign_item["id"]])
    with pytest.raises(ValueError, match="belongs to deployment run 'run-foreign'"):
        cmd_add_item("run-selection", 9421, requirement_ids=[foreign_run["id"]])
