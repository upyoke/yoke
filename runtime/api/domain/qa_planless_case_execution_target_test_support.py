# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain.qa_case_execution_context import (
    QaCaseExecutionError,
    get_case_execution_context,
)

from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements


def _environment(conn, *, name: str, url: str | None = None, settings: str = "{}"):
    site = conn.execute(
        "INSERT INTO sites (project_id, name, created_at) "
        "VALUES (1, %s, %s) RETURNING id",
        (f"site-{name}", "2026-09-17T00:00:00Z"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments (site, project_id, name, url, settings, "
        "created_at) VALUES (%s, 1, %s, %s, %s, %s)",
        (int(site), name, url, settings, "2026-09-17T00:00:00Z"),
    )
    conn.commit()
