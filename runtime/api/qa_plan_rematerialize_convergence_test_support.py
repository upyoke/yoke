# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)

from runtime.api.fixtures.pg_testdb import test_database

from runtime.api.qa_catalog_test_support import CATALOG_CASES

from yoke_core.domain.qa_deployment_case_content_refresh import (
    case_content_digest,
    refreshed_case_keys,
)

from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

from yoke_core.domain.qa_requirement_replacement import (
    declare_existing_replacement,
)

MEMBER = 9861


def _case(key: str, instructions: str, position: int = 1) -> dict:
    return {
        "case_key": key,
        "position": position,
        "method_id": "command",
        "instructions": instructions,
        "expected_outcome": "the command passes",
        "method_config": {"command": "true"},
    }


def _plan_id(conn, requirement_id: int) -> int:
    return int(
        conn.execute(
            "SELECT plan_id FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()["plan_id"]
    )


def _stage(conn, run_id: str) -> dict:
    return {
        "deployment_run_id": run_id,
        "deployment_stage": ITEM_QA_STAGE,
        "deployment_member_item_id": MEMBER,
    }


def _two_case_stage(conn, run_id: str) -> tuple[int, int, int]:
    """A stage holding the seeded case plus one the plan gained afterwards."""
    first = seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)
    plan_id = _plan_id(conn, first)
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            _case("command-smoke", "run the frozen smoke command", 1),
            _case("second-smoke", "run the second smoke command", 2),
        ],
    )
    conn.commit()
    result = rematerialize_for_deployment_stage(conn, **_stage(conn, run_id))
    assert len(result["created_requirement_ids"]) == 1
    return plan_id, first, int(result["created_requirement_ids"][0])
