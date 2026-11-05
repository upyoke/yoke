# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain import dependency_satisfied_notice as notice

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode

from yoke_core.domain.work_claim_targets import make_item_target

BLOCKER = 9851

DEPENDENT = 9853


def _edge(conn: Any, blocker: int, gate_point: str, satisfaction: str) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', '', %s)",
        (DEPENDENT, blocker, gate_point, satisfaction, "2026-01-02T00:00:00Z"),
    )
    conn.commit()


def _parked_dependent(conn: Any) -> None:
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(DEPENDENT).scope_json(),
    )
    set_session_mode(conn, HOLDER_A, SESSION_MODE_PARKED, "awaiting blocker merge")


def _key(conn: Any, gate_point: str) -> str:
    row = conn.execute(
        "SELECT id FROM item_dependencies WHERE dependent_item_id=%s "
        "AND blocking_item_id=%s AND gate_point=%s",
        (DEPENDENT, BLOCKER, gate_point),
    ).fetchone()
    return notice.dependency_satisfied_key(DEPENDENT, BLOCKER, gate_point, row[0])
