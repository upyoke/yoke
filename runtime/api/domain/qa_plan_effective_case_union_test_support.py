# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict

from runtime.api.fixtures.qa_declared_replacement_fixture import corrected_case, declare

from yoke_core.domain.qa_plan_case_proof import _case_result

from yoke_core.domain.qa_plan_detail import get_plan

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_summary import plan_summary


def _cases(conn, plan_id, keys):
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": "Run the corrected command.",
                "expected_outcome": "It passes.",
                "method_config": {"command": "true"},
            }
            for position, key in enumerate(keys, 1)
        ],
    )


def _replacement(conn):
    item = insert_item(conn, title="Effective case union")
    plan = create_plan(
        conn, project="yoke", slug="effective-case-union", name="Effective cases"
    )
    plan_id = int(plan["id"])
    _cases(conn, plan_id, ["original", "corrected"])
    old_id = int(
        insert_qa_requirement(
            conn,
            item_id=item["id"],
            plan_id=plan_id,
            plan_case_key="original",
            method_id="command",
            qa_kind="plan_case",
            method_config='{"command":"true"}',
        )["id"]
    )
    record_case_verdict(conn, old_id, "fail", evidence=False)
    successor = corrected_case(conn, failed_id=old_id, case_key="corrected")
    declare(conn, old_id, "corrected", [successor])
    return plan_id, old_id, successor
