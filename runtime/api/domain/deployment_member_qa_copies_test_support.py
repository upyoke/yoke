# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_run

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _original_requirement,
)

from runtime.api.fixtures.completed_delivery import seed_selected_requirement_run

from runtime.api.fixtures.deployment_admitted_case_fixture import admitted_copy

from yoke_core.domain.deployment_member_qa_projection import member_qa_obligations

from yoke_core.domain.db_helpers import query_rows


def read(conn, run_id, members):
    runs = query_rows(
        conn,
        "SELECT dr.*,df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
        (run_id,),
    )
    items = [
        {"id": member, "ref": f"SAMPLE-{member}", "project_id": 1, "project": "yoke"}
        for member in members
    ]
    return member_qa_obligations(conn, runs, {run_id: items})
