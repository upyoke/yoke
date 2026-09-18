"""A run-wide QA materialization is refused where a stage counts members.

An item-scoped QA stage credits a member only through a requirement carrying
that stage and that member. A plan materialized run-wide carries neither, so
the owner could run it, record a real pass, and leave the stage waiting for
evidence that could not reach it. Three owners on one release did exactly
that before the write refused.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_deployment_run_stage_scope import (
    item_scoped_qa_stages,
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


def _run(conn, stages: str) -> None:
    insert_deployment_run(conn, id=RUN_ID, status="executing")
    conn.execute(
        "UPDATE deployment_flows SET stages=%s "
        "WHERE id=(SELECT flow FROM deployment_runs WHERE id=%s)",
        (stages, RUN_ID),
    )
    conn.commit()


def test_a_run_pinning_an_item_scoped_stage_reports_it() -> None:
    with test_database() as conn:
        _run(conn, ITEM_SCOPED_STAGES)

        assert item_scoped_qa_stages(conn, RUN_ID) == ["item-qa"]


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
    assert "item-scoped QA stage 'item-qa'" in message
    assert (
        f"--deployment-run-id {RUN_ID} --stage item-qa --member PREFIX-N "
        "--plan release-boundary-qa --project yoke" in message
    )


def test_a_run_scoped_qa_stage_leaves_the_run_wide_write_alone() -> None:
    with test_database() as conn:
        _run(conn, RUN_SCOPED_STAGES)

        assert item_scoped_qa_stages(conn, RUN_ID) == []
        require_stage_scoped_materialization(
            conn,
            deployment_run_id=RUN_ID,
            plan="release-boundary-qa",
            project="yoke",
        )
