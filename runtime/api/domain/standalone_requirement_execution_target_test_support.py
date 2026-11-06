# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.qa_review_seed import resolve_capture_review

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement

from runtime.api.fixtures.pg_testdb import test_database

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers import qa_requirement_create

from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
)

from yoke_core.domain.qa_requirement_config_update import apply_requirement_update

from yoke_core.domain.qa_requirement_pass_currency import (
    has_current_passing_run,
    recorded_method_config,
    stamp_executed_method_config,
)

from yoke_core.domain.qa_review_requests import apply_qa_review_resolution

from yoke_core.domain.qa_workflow_binding_validation import item_transition_for_gate

from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION

PREVIEW_URL = "http://127.0.0.1:8931"

TRANSITION = "implemented"


def _request(item_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _bound_browser_payload(conn, item_id: int, **extra) -> dict:
    payload = {
        "method_id": "browser-inspection",
        "qa_phase": "verification",
        "instructions": "Inspect the preview surface.",
        "expected_outcome": "The preview is reachable.",
        "method_config": {
            "base_url": PREVIEW_URL,
            "steps": [
                {"action": "navigate", "route": "/"},
                {"action": "screenshot", "capture": True},
            ],
        },
        "workflow_transition_id": item_transition_for_gate(
            conn,
            item_id=item_id,
            gate_id=GATE_QA_VERIFICATION,
        ),
    }
    payload.update(extra)
    return payload


def _environment(conn, *, project_id: int, name: str, url: str | None = None) -> None:
    site = conn.execute(
        "INSERT INTO sites (project_id, name, created_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        (int(project_id), f"site-{project_id}-{name}", "2026-09-17T00:00:00Z"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments (site, project_id, name, url, settings, "
        "created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            int(site),
            int(project_id),
            name,
            url,
            json.dumps({"hosts": {"app": url}} if url else {}),
            "2026-09-17T00:00:00Z",
        ),
    )
    conn.commit()
