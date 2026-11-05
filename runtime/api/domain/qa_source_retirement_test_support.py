# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.domain.dash_post_deploy_review_isolation_test_support import (
    _insert_dash,
)

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _seed_selected_requirement_run,
)

from runtime.api.domain.release_member_target_enrollment_test_support import _pair

from runtime.api.fixtures.deployment_admitted_case_fixture import (
    MEMBER_QA_STAGE,
    admitted_copy,
    deliver_with_failing_admitted_copy,
    succeed_run,
)

from yoke_core.domain.dash_posture_gate import evaluate

from yoke_core.domain.deployment_member_post_deploy_admission import (
    admissible_post_deploy_requirement_ids,
)

from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)

from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.qa_requirement_supersession import (
    QaSupersessionError,
    supersede_requirement,
)

CORRECTED_INSTRUCTIONS = "Open the release workbench and capture its ready state."


def _corrected_item_requirement(conn, *, source_id: int) -> int:
    """The source's own subject and target with a corrected body."""
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    projected = [
        "%s"
        if column == "instructions"
        else "NULL"
        if column.startswith("supersed") or column == "replacement_requirement_id"
        else column
        for column in columns
    ]
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) "
        f"SELECT {','.join(projected)} FROM qa_requirements WHERE id=%s "
        "RETURNING id",
        (CORRECTED_INSTRUCTIONS, int(source_id)),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def _retire(conn, *, source_id: int, corrected_id: int) -> dict:
    return supersede_requirement(
        conn,
        requirement_id=source_id,
        superseded_by_requirement_id=corrected_id,
        rationale="the source named the wrong route; the corrected body passed",
        source="agent",
    )
