# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.backlog import insert_item

from runtime.api.fixtures.backlog_insert_support import ensure_project_id

from runtime.api.fixtures.session_holdings import (
    insert_session as _seed_session,
    insert_steering_claim,
    instant_ago,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain import backlog_close_op, backlog_update_op

from yoke_core.domain.sessions_lifecycle_claim import claim_work

from yoke_core.domain.work_claim_targets import make_item_target

from yoke_core.domain.handlers.items_cancel import handle_cancel

from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)

from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION

SESSION = "cancel-verb-session"


@pytest.fixture(autouse=True)
def _isolate_write_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(backlog_update_op, "run_post_db_sync", lambda **_kwargs: 0)
    monkeypatch.setattr(
        backlog_close_op._rendering, "_post_comment", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        backlog_close_op._rendering, "_close_issue", lambda *_a, **_k: None
    )


@pytest.fixture(autouse=True)
def _caller_session(test_db) -> None:
    _seed_session(test_db, SESSION)


def _live_claims(conn: Any, item_id: int) -> list:
    target = make_item_target(item_id)
    rows = conn.execute(
        "SELECT session_id FROM work_claims "
        "WHERE target_kind = %s AND scope = %s AND released_at IS NULL",
        (target.kind, target.scope_json()),
    ).fetchall()
    return [str(row["session_id"]) for row in rows]


def _request(item_id: int, **payload: Any) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.cancel.run",
        actor=ActorContext(actor_id="1", session_id=SESSION),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )
