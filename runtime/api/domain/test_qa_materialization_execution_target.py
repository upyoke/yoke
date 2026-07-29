"""Fail-closed target identity for idempotent QA materialization."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)


def _materialize_command_plan(conn, *, item_id: int) -> dict:
    insert_item(
        conn,
        id=item_id,
        title="Run targeted QA",
        workflow_id="issue",
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"targeted-plan-{item_id}",
        name="Targeted plan",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the target command.",
                "expected_outcome": "The command passes.",
                "method_config": {"command": "true"},
            }
        ],
    )
    set_project_default(
        conn,
        plan_id=int(plan["id"]),
        workflow_id="issue",
        transition_id="implemented",
    )
    return materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="implemented",
    )


def test_legacy_unbound_rows_are_not_silently_reused() -> None:
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=821)
        requirement_id = result["created_requirement_ids"][0]
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=NULL,"
            "execution_target_digest=NULL WHERE id=%s",
            (requirement_id,),
        )
        conn.commit()

        with pytest.raises(
            QaPlanError,
            match="legacy QA requirement.*start a fresh",
        ):
            materialize_for_item(
                conn,
                item_id=821,
                transition_id="implemented",
            )


def test_rows_bound_to_another_target_are_not_silently_reused() -> None:
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=822)
        requirement_id = result["created_requirement_ids"][0]
        raw = conn.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()["execution_target_json"]
        other_target = json.loads(raw)
        other_target["environment"] = {
            "id": "yoke-api-stage",
            "name": "stage",
        }
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=%s,"
            "execution_target_digest=%s WHERE id=%s",
            (
                canonical_target(other_target),
                target_digest(other_target),
                requirement_id,
            ),
        )
        conn.commit()

        with pytest.raises(
            QaPlanError,
            match="different execution target.*start a fresh",
        ):
            materialize_for_item(
                conn,
                item_id=822,
                transition_id="implemented",
            )


def test_matching_target_rows_are_reused_idempotently() -> None:
    with test_database() as conn:
        first = _materialize_command_plan(conn, item_id=823)
        second = materialize_for_item(
            conn,
            item_id=823,
            transition_id="implemented",
        )

    assert second["created_requirement_ids"] == []
    assert second["existing_requirement_ids"] == first["created_requirement_ids"]


def test_fresh_target_bound_rows_start_a_durable_execution() -> None:
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=824)
        execution = begin_plan_execution(
            conn,
            item_id=824,
            transition_id="implemented",
            actor_id="actor-824",
            session_id="session-824",
        )

    assert execution["execution_target"]["environment"]["name"] == "development"
    assert execution["execution_target_digest"]
    assert execution["roster"][0]["requirement_id"] == (
        result["created_requirement_ids"][0]
    )
