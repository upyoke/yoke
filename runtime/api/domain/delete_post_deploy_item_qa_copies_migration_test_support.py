# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import importlib

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run

from yoke_core.domain.migration_serving_version import NEXT_RELEASE

from yoke_core.domain.schema_expected_catalog import parse_expected_schema

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0094_delete_post_deploy_item_qa_copies"
)


def _plan(conn, slug="smoke") -> int:
    return int(
        conn.execute(
            "INSERT INTO qa_plans (project_id, slug, name, created_at, updated_at) "
            "VALUES (1, %s, 'Smoke', '2026-10-28T00:00:00Z', '2026-10-28T00:00:00Z') "
            "RETURNING id",
            (slug,),
        ).fetchone()[0]
    )


def _copy(conn, item_id, plan_id, **extra) -> int:
    return int(
        insert_qa_requirement(
            conn,
            item_id=item_id,
            qa_kind="plan_case",
            qa_phase="post_deploy",
            plan_id=plan_id,
            **{"plan_case_key": "home", **extra},
        )["id"]
    )


def _member(conn, run_id, item_id, snapshot=None) -> None:
    conn.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at, requirement_snapshot) "
        "VALUES (%s, %s, '2026-10-28T00:00:00Z', %s)",
        (run_id, item_id, json.dumps(snapshot or {"schema": 1, "requirements": []})),
    )
