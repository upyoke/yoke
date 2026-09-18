"""A run-wide QA materialization is refused where any QA stage counts by name.

Stage acceptance reads `deployment_stage = <name>`, and an item-scoped stage
reads its member item too. A plan materialized run-wide carries neither, so
the owner could run it, record a real pass, and leave the stage waiting for
evidence that could not reach it. Three owners on one release did exactly
that before the write refused. A run-scoped stage filters on its own name
just the same, so the refusal covers it rather than only the item-scoped
case.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_deployment_run_stage_scope import (
    pinned_qa_stages,
    require_stage_scoped_materialization,
)
from yoke_core.domain.qa_plan_management import QaPlanError

RUN_ID = "run-20260101-004"
ITEM_SCOPED_STAGES = json.dumps(
    [
        {"name": "release-prod", "stage_kind": "execution"},
        {
            "name": "item-qa",
            "stage_kind": "qa",
            "step_runner": "qa",
            "scope": "item",
        },
    ]
)
RUN_SCOPED_STAGES = json.dumps(
    [
        {
            "name": "release-qa",
            "stage_kind": "qa",
            "step_runner": "qa",
            "scope": "run",
        },
    ]
)
BOTH_SCOPED_STAGES = json.dumps(
    [
        {
            "name": "item-qa",
            "stage_kind": "qa",
            "step_runner": "qa",
            "scope": "item",
        },
        {
            "name": "release-qa",
            "stage_kind": "qa",
            "step_runner": "qa",
            "scope": "run",
        },
    ]
)
NO_QA_STAGES = json.dumps([{"name": "release-prod", "stage_kind": "execution"}])


def _run(conn, stages: str) -> None:
    insert_deployment_run(conn, id=RUN_ID, status="executing")
    conn.execute(
        "UPDATE deployment_flows SET stages=%s "
        "WHERE id=(SELECT flow FROM deployment_runs WHERE id=%s)",
        (stages, RUN_ID),
    )
    conn.commit()


def test_a_run_pinning_an_item_scoped_stage_reports_it_with_its_scope() -> None:
    with test_database() as conn:
        _run(conn, ITEM_SCOPED_STAGES)

        assert pinned_qa_stages(conn, RUN_ID) == [
            {"name": "item-qa", "scope": "item"}
        ]


def test_the_run_wide_write_is_refused_with_the_binding_invocation() -> None:
    with test_database() as conn:
        _run(conn, ITEM_SCOPED_STAGES)

        with pytest.raises(QaPlanError) as refusal:
            require_stage_scoped_materialization(
                conn,
                deployment_run_id=RUN_ID,
                plan="release-boundary-qa",
                project="yoke",
            )

    message = str(refusal.value)
    assert "pins QA stage(s) 'item-qa' (scope item)" in message
    assert (
        f"--deployment-run-id {RUN_ID} --stage item-qa --member PREFIX-N "
        "--plan release-boundary-qa --project yoke" in message
    )


def test_a_run_scoped_stage_refuses_it_too_and_names_no_member() -> None:
    with test_database() as conn:
        _run(conn, RUN_SCOPED_STAGES)

        assert pinned_qa_stages(conn, RUN_ID) == [
            {"name": "release-qa", "scope": "run"}
        ]
        with pytest.raises(QaPlanError) as refusal:
            require_stage_scoped_materialization(
                conn,
                deployment_run_id=RUN_ID,
                plan="release-boundary-qa",
                project="yoke",
            )

    message = str(refusal.value)
    assert (
        f"--deployment-run-id {RUN_ID} --stage release-qa --plan "
        "release-boundary-qa --project yoke" in message
    )
    assert "--stage release-qa --member" not in message


def test_the_refusal_names_every_pinned_qa_stage() -> None:
    with test_database() as conn:
        _run(conn, BOTH_SCOPED_STAGES)

        with pytest.raises(QaPlanError) as refusal:
            require_stage_scoped_materialization(
                conn,
                deployment_run_id=RUN_ID,
                plan="release-boundary-qa",
                project="yoke",
            )

    message = str(refusal.value)
    assert "'item-qa'" in message
    assert "'release-qa'" in message
    assert "--stage item-qa --member PREFIX-N" in message
    assert "--stage release-qa --plan" in message


def test_a_run_with_no_qa_stage_keeps_the_run_wide_write() -> None:
    with test_database() as conn:
        _run(conn, NO_QA_STAGES)

        assert pinned_qa_stages(conn, RUN_ID) == []
        require_stage_scoped_materialization(
            conn,
            deployment_run_id=RUN_ID,
            plan="release-boundary-qa",
            project="yoke",
        )
