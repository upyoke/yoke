"""A release whose flow binds a second project's trunk, built for real.

Binding-based delivery is only meaningful against two actual repositories
and two actual projects: the record exists so that what a run shipped and
what it is later judged on are the same commit. Tests that stubbed the
resolution would pass while the comparison behind membership and delivery
quietly stopped being readable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_insert_support import ensure_project_id
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    bound_source_repository,
    insert_run,
    item_ref,
    serve_repositories,
    stage_environment,
)
from yoke_core.domain.flow_create import cmd_create


CARRIER_FLOW = "carrier-release-flow"
CONSUMER_FLOW = "consumer-release-flow"
CONSUMER_PROJECT = "consumer"
CARRIER_ITEM_ID = 9601
CONSUMER_ITEM_ID = 9602
UNBOUND_ITEM_ID = 9603
UNBOUND_PROJECT = "bystander"
SEEDED_AT = "2026-09-14T00:00:00Z"


def bound_stages(*, project: str = CONSUMER_PROJECT, branch: str = "main") -> str:
    return json.dumps(
        [
            {
                "name": "hosted-release",
                "step_runner": "github-actions-workflow",
                "workflow": "release.yml",
                "stage_kind": "execution",
                "scope": "run",
                "input_bindings": {
                    "consumer_sha": {"project": project, "branch": branch}
                },
                "inputs": {"consumer_sha": "{consumer_sha}"},
            }
        ]
    )


def stages_with_item_qa() -> str:
    stages = json.loads(bound_stages())
    stages.append(
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "hosted-release",
            },
            "verdict": {"mode": "agent_only"},
        }
    )
    return json.dumps(stages)


def _plain_stages() -> str:
    return json.dumps(
        [
            {
                "name": "stage",
                "step_runner": "auto",
                "stage_kind": "execution",
                "scope": "run",
            }
        ]
    )


def _project_id(conn: Any, slug: str) -> int:
    row = conn.execute(
        "SELECT id FROM projects WHERE slug=%s", (slug,)
    ).fetchone()
    return int(row[0])


def two_project_release(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    consumer_status: str = "implementing",
    stages: str | None = None,
    consumer_names_item: bool = True,
) -> dict[str, Any]:
    """A carrier run whose flow binds a consumer project's trunk.

    ``consumer_names_item=False`` gives the consumer's landing commit a
    message that attributes nothing, so a test can prove which recorded
    evidence rung carries the attribution on the bound path.
    """
    stage_environment(conn)
    ensure_project_id(conn, CONSUMER_PROJECT, ts=SEEDED_AT)
    conn.commit()
    cmd_create(
        conn, CARRIER_FLOW, "yoke", "Carrier", "",
        stages if stages is not None else bound_stages(), status="disabled",
    )
    cmd_create(
        conn, CONSUMER_FLOW, CONSUMER_PROJECT, "Consumer", "",
        _plain_stages(), status="disabled",
    )
    insert_item(
        conn, id=CARRIER_ITEM_ID, project_sequence=CARRIER_ITEM_ID,
        workflow_id="blitz", status="implementing", deployment_flow=CARRIER_FLOW,
    )
    insert_item(
        conn, id=CONSUMER_ITEM_ID, project_sequence=CONSUMER_ITEM_ID,
        workflow_id="blitz", status=consumer_status, project=CONSUMER_PROJECT,
        deployment_flow=CONSUMER_FLOW,
    )
    conn.commit()
    carrier_ref = item_ref(conn, CARRIER_ITEM_ID)
    consumer_ref = item_ref(conn, CONSUMER_ITEM_ID)
    consumer_id = _project_id(conn, CONSUMER_PROJECT)
    carrier_repo, carrier_base, carrier_tip = bound_source_repository(
        tmp_path, "carrier", carrier_ref
    )
    consumer_repo, consumer_base, consumer_tip = bound_source_repository(
        tmp_path, "consumer", consumer_ref, names_item=consumer_names_item
    )
    serve_repositories(monkeypatch, {1: carrier_repo, consumer_id: consumer_repo})
    insert_run(
        conn, "run-previous", lineage=carrier_base, status="succeeded",
        flow=CARRIER_FLOW,
        bound_sources=json.dumps(
            {
                "schema": 1,
                "projects": [
                    {
                        "project": CONSUMER_PROJECT,
                        "project_id": consumer_id,
                        "commit_sha": consumer_base,
                    }
                ],
                "inputs": {"consumer_sha": consumer_base},
            }
        ),
    )
    insert_run(
        conn, "run-candidate", lineage=carrier_tip, status="created",
        flow=CARRIER_FLOW,
    )
    return {
        "carrier_ref": carrier_ref,
        "consumer_ref": consumer_ref,
        "consumer_id": consumer_id,
        "consumer_repo": consumer_repo,
        "consumer_base": consumer_base,
        "consumer_tip": consumer_tip,
    }


__all__ = [
    "CARRIER_FLOW",
    "CARRIER_ITEM_ID",
    "CONSUMER_FLOW",
    "CONSUMER_ITEM_ID",
    "CONSUMER_PROJECT",
    "UNBOUND_ITEM_ID",
    "UNBOUND_PROJECT",
    "bound_stages",
    "stages_with_item_qa",
    "two_project_release",
]
