# ruff: noqa: F811
"""Deployment composition consumes the canonical dependency evaluator."""

from __future__ import annotations

import json
from typing import Any

from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    db_path,
)
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin


NOW = "2026-09-03T12:00:00Z"


def _insert_item(conn: Any, item_id: int) -> None:
    workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
    conn.execute(
        "INSERT INTO items "
        "(id,title,workflow_id,workflow_version_id,status,project_id,"
        "project_sequence,merged_at,created_at,updated_at) "
        "VALUES (%s,'item',%s,%s,'implemented',1,%s,%s,%s,%s)",
        (
            item_id,
            workflow_id,
            workflow_version_id,
            item_id,
            NOW,
            NOW,
            NOW,
        ),
    )


def _seed_validation(db_path: str, *, with_delivery_fact: bool) -> str:
    current_run = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    conn = _conn(db_path)
    _insert_item(conn, 100)
    _insert_item(conn, 200)
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
        "VALUES (100,200,'activation','fact:deployed:prod','test',%s)",
        (NOW,),
    )
    conn.commit()
    conn.close()
    dr.cmd_add_item(current_run, 100, db_path=db_path)
    if with_delivery_fact:
        prior_run = dr.cmd_create_run(
            "yoke",
            "yoke-internal",
            environment="prod",
            db_path=db_path,
        )
        conn = _conn(db_path)
        conn.execute(
            "UPDATE deployment_runs SET status='succeeded',carried_work=%s "
            "WHERE id=%s",
            (json.dumps({"schema": 1, "items": [{"item_id": 200}]}), prior_run),
        )
        conn.commit()
        conn.close()
    return current_run


def test_composition_accepts_a_prior_succeeded_delivery(db_path: str) -> None:
    run_id = _seed_validation(db_path, with_delivery_fact=True)
    assert dr.cmd_validate_composition(run_id, db_path=db_path) == (True, "OK")


def test_composition_reports_missing_environment_delivery(db_path: str) -> None:
    run_id = _seed_validation(db_path, with_delivery_fact=False)
    ok, message = dr.cmd_validate_composition(run_id, db_path=db_path)
    assert ok is False
    assert "merged, not yet deployed to prod" in message
