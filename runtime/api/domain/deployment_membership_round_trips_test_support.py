# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any, Callable

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)

from runtime.api.tools.read_query_profile import CountedConnection

from yoke_core.domain import deployment_run_candidate_containment as containment

from yoke_core.domain import deployment_run_composition_freeze as composition

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_run_member_admission import (
    MemberAdmission,
    admit_run_items,
)

from yoke_core.domain.deployment_run_start import _admit

from yoke_core.domain.deployment_run_target_takeover import take_over_waiting_run

from yoke_core.domain.schema_read_scope import composition_reads


def _statements(conn: Any, operation: Callable[[Any], Any]) -> int:
    """Statements *operation* sends inside one production-shaped read scope."""
    counted = CountedConnection(conn)
    with composition_reads():
        operation(counted)
    conn.commit()
    return sum(counted.counts.values())


def _members(base: int, count: int) -> list[int]:
    return [base + offset for offset in range(count)]


def _created_run(conn: Any, name: str, members: list[int]) -> str:
    """A created run whose flow takes custody, and delivery-ready items."""
    run_id, flow = f"run-{name}", f"flow-{name}"
    stages = [
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
        },
    ]
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version,takes_delivery_custody) "
        "VALUES (%s,1,%s,'',%s,%s,'disabled',2,1)",
        (flow, flow, json.dumps(stages), "2026-09-14T00:00:00Z"),
    )
    for item_id in members:
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="blitz",
            status="implementing",
            deployment_flow=flow,
        )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at,composition_resolution) VALUES "
        "(%s,1,%s,%s,'created',%s,'baseline attested')",
        (run_id, flow, "a" * 40, "2026-09-14T00:00:00Z"),
    )
    conn.commit()
    return run_id


def _admit_all(run_id: str, members: list[int]) -> Callable[[Any], Any]:
    return lambda conn: admit_run_items(
        conn, run_id=run_id, members=[MemberAdmission(item) for item in members]
    )
