# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run

from typing import Any

import pytest

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
)

from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _landing_evidence,
    _no_obligation,
    _ready_member,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from yoke_core.domain import delivery_member_close_steps as close_out

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain.work_claim_target_sql import scope_int_sql

FIRST_ITEM = 9841

SECOND_ITEM = 9842

REASON = "nothing observable once deployed"


def _executing_run(conn: Any, run_id: str, members: tuple[int, ...]) -> None:
    now = iso8601_now()
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=1,
        flow=COMPLETION_FLOW,
        status="executing",
        created_at=now,
    )
    from runtime.api.fixtures.completed_delivery import pin_run_delivery

    pin_run_delivery(conn, run_id)
    for item_id in members:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _run(conn: Any, run_id: str) -> tuple[str, bool]:
    row = conn.execute(
        "SELECT status,settling_at FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    return str(row["status"]), bool(row["settling_at"])


def _status(conn: Any, item_id: int) -> str:
    return conn.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
        "status"
    ]


def _claim_held(conn: Any, item_id: int) -> bool:
    item_scope = scope_int_sql(conn, "scope", "item_id")
    return (
        conn.execute(
            "SELECT id FROM work_claims WHERE target_kind='item' "
            f"AND released_at IS NULL AND {item_scope}=%s",
            (item_id,),
        ).fetchone()
        is not None
    )
