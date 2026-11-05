# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from yoke_core.domain import qa

from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_REVISION_KEY,
    has_current_passing_run,
    recorded_method_config,
)

from runtime.api.fixtures.file_test_db import connect_test_db

from runtime.api.qa_test_helpers import make_qa_db_file

from runtime.api.qa_transition_test_support import QA_GATED_TRANSITION

_OLD_STEPS = [
    {"action": "navigate", "route": "/dashboard"},
    {"action": "assert", "target": "[data-old=true]", "check": "visible"},
]

_NEW_STEPS = [
    {"action": "navigate", "route": "/dashboard"},
    {"action": "wait_for", "target": "[data-ready=true]"},
    {"action": "assert", "target": "[data-ready=true]", "check": "visible"},
    {"action": "screenshot", "capture": True},
]

_NOW = "2026-04-20T00:00:00Z"


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _seed_requirement(db_path: str, *, method_id: str, config: dict) -> int:
    req_id = qa.cmd_requirement_add(
        db_path=db_path,
        item_id=42,
        qa_kind="plan_case",
        qa_phase="verification",
        workflow_transition_id=QA_GATED_TRANSITION,
    )
    conn = connect_test_db(db_path)
    conn.execute(
        "UPDATE qa_requirements SET method_id = %s, method_config = %s WHERE id = %s",
        (method_id, json.dumps(config), req_id),
    )
    conn.commit()
    conn.close()
    return req_id


def _seed_browser_requirement(db_path: str, *, steps: list[dict]) -> int:
    return _seed_requirement(
        db_path, method_id="browser-check", config={"steps": steps}
    )


def _insert_unstamped_pass(db_path: str, req_id: int) -> tuple[int, str | None]:
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, verdict, raw_result, created_at,started_at,completed_at) VALUES (%s, %s, %s, %s, %s, %s,%s,%s) RETURNING id",
        (
            req_id,
            "browser_substrate",
            "plan_case",
            "pass",
            "legacy capture evidence",
            _NOW,
            _NOW,
            _NOW,
        ),
    )
    run_id = int(cur.fetchone()[0])
    raw = conn.execute(
        "SELECT raw_result FROM qa_runs WHERE id = %s", (run_id,)
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return run_id, raw
