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

from yoke_core.domain.qa_requirement_snapshot_validation import SNAPSHOT_COLUMNS

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
