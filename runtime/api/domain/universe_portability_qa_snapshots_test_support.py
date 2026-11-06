# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.universe_portability_test_support import (
    _canonical_test_universe,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain import universe_portability as portability

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_requirement_snapshot_convergence import SNAPSHOT_COLUMNS

from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)


def _create_requirement_source(
    conn,
    *,
    item_id: int,
    slug: str,
    host_baselines: list[str],
) -> tuple[int, int]:
    insert_item(
        conn,
        id=item_id,
        title="Portable requirement snapshot",
        workflow_id="issue",
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=slug,
        name="Portable requirement snapshot",
    )
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "portable-command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the portable command.",
                "expected_outcome": "The portable command passes.",
                "method_config": {"command": "true"},
            }
        ],
    )
    if host_baselines:
        # An older archive predates per-case starting states, so its plan
        # cases may still name baselines that authoring now refuses.
        conn.execute(
            "UPDATE qa_plan_cases SET host_baselines=%s WHERE plan_id=%s",
            (json.dumps(host_baselines), plan["id"]),
        )
    return int(plan["id"]), item_id


def seed_older_requirement_snapshot(source):
    plan_id, item_id = _create_requirement_source(
        source,
        item_id=88106,
        slug="portable-requirement-snapshot",
        host_baselines=["legacy-host"],
    )
    requirement_id = int(
        source.execute(
            "INSERT INTO qa_requirements("
            "item_id, qa_kind, qa_phase, blocking_mode, "
            "requirement_source, plan_id, plan_case_key, method_id, "
            "host_baseline, workflow_transition_id, instructions, "
            "expected_outcome, method_config, created_at"
            ") VALUES (%s, 'plan_case', 'verification', 'blocking', "
            "'flow_derived', %s, 'portable-command', 'command', "
            "'legacy-host', 'implemented', 'Run the portable command.', "
            "'The portable command passes.', '{\"command\":\"true\"}', "
            "'2026-10-01T00:00:00Z') RETURNING id",
            (item_id, plan_id),
        ).fetchone()[0]
    )
    for column in SNAPSHOT_COLUMNS:
        source.execute(f"ALTER TABLE qa_requirements DROP COLUMN IF EXISTS {column}")
    source.commit()
    return requirement_id


def assert_requirement_snapshot_restored(target, requirement_id):
    assert target.execute(
        "SELECT case_position, baseline_position, method_name, "
        "runner_id, capability_requirements, verdict_path "
        "FROM qa_requirements WHERE id = %s",
        (requirement_id,),
    ).fetchone() == (
        1,
        1,
        "Command",
        "worktree_run",
        "[]",
        "automatic",
    )
