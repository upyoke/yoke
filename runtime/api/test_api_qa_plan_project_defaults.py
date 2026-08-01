"""Project-default QA plan attach/detach contract tests."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import create_release_readiness_plan
from yoke_core.domain.qa_plan_attachments import (
    has_attached_plans,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_project_defaults import (
    set_project_default,
    unset_project_default,
)


def test_multiple_project_default_plans_share_one_transition() -> None:
    with test_database() as conn:
        item = insert_item(
            conn,
            id=42,
            title="Ship checkout",
            workflow_id="issue",
            status="implemented",
        )
        release = create_release_readiness_plan(conn)
        lint = create_plan(
            conn,
            project="yoke",
            slug="lint-command",
            name="Lint command",
        )
        replace_plan_cases(
            conn,
            plan_id=lint["id"],
            cases=[{
                "case_key": "lint",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the registered lint command.",
                "expected_outcome": "The command exits successfully.",
                "method_config": {"command": "ruff check ."},
            }],
        )
        for plan in (release, lint):
            set_project_default(
                conn,
                plan_id=plan["id"],
                workflow_id=str(item["workflow_id"]),
                transition_id="release",
            )
        materialized = materialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )

    assert set(materialized["plan_ids"]) == {release["id"], lint["id"]}
    assert len(materialized["created_requirement_ids"]) == 3


def test_unset_project_default_detaches_only_the_named_transition() -> None:
    with test_database() as conn:
        item = insert_item(conn, id=77, project_sequence=77)
        plan = create_release_readiness_plan(conn)
        for transition in ("release", "reviewing-implementation"):
            set_project_default(
                conn,
                plan_id=plan["id"],
                workflow_id=str(item["workflow_id"]),
                transition_id=transition,
            )
        removed = unset_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id=str(item["workflow_id"]),
            transition_id="release",
        )
        assert removed["transition_id"] == "release"
        assert not has_attached_plans(
            conn, item_id=int(item["id"]), transition_id="release"
        )
        assert has_attached_plans(
            conn,
            item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        with pytest.raises(QaPlanError, match="not a project default"):
            unset_project_default(
                conn,
                plan_id=plan["id"],
                workflow_id=str(item["workflow_id"]),
                transition_id="release",
            )
