# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

from runtime.api.domain.independent_member_delivery_close_out_test_support import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)

from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _no_obligation,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from yoke_core.domain.decision_request_resolution import resolve_decision_request

from yoke_core.domain.decision_request_schema import create_decision_request_tables

from yoke_core.domain.schema_work_claim_sql import scope_int_sql

RUN_ID = "run-done-approval"


def _approval_members(conn: Any, *members: int) -> None:
    """Each member owes a done approval and no post-deploy check."""
    create_decision_request_tables(conn)
    _seed_final_run(conn, RUN_ID, shared_qa=False)
    for item_id in members:
        conn.execute(
            "UPDATE items SET workflow_posture=%s WHERE id=%s",
            (json.dumps({"approval_on_done": True}), item_id),
        )
        _no_obligation(conn, item_id, reason="nothing observable once deployed")
    conn.commit()
    for item_id in members:
        _settle(conn, run_id=RUN_ID, stage="item-qa", member=item_id)


def _done_request(conn: Any, item_id: int) -> Any:
    return conn.execute(
        "SELECT id,status,consumed_at FROM decision_requests "
        "WHERE kind='lifecycle_transition_approval' AND subject_key=%s "
        "ORDER BY id DESC LIMIT 1",
        (f"{item_id}:done",),
    ).fetchone()


def _owner(conn: Any) -> int:
    return int(
        conn.execute(
            "SELECT apr.actor_id FROM actor_project_roles apr "
            "JOIN roles r ON r.id=apr.role_id JOIN actors a ON a.id=apr.actor_id "
            "WHERE apr.project_id=1 AND r.name='owner' AND a.kind='human' "
            "ORDER BY apr.actor_id LIMIT 1"
        ).fetchone()[0]
    )
