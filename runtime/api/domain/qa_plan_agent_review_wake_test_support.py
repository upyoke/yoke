# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)

from runtime.api.domain.qa_capture_pending_review_test_support import (
    MEMBER,
    STAGE,
    _seed_pending,
    _submit,
)

from yoke_core.domain.deployment_qa_stage_wake import notify_item_scoped_qa_wait

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain.qa_plan_agent_review_wake import notify_scoped_agent_review

from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution

from yoke_core.domain.qa_plan_review import begin_plan_review

from yoke_core.domain.qa_plan_settled_review import (
    SETTLED_REVIEW_WAKE_REASON,
    open_unsettled_roster,
    withdraw_settled_agent_review_wakes,
)

from yoke_core.domain.session_explicit_wake import explicit_stopped_wake_requested

from yoke_core.domain.work_claim_targets import make_item_target

OWNER = "capture-session"


def _owner(conn, *, executor="claude-code", surface="claude-cli"):
    _project(conn)
    seed_session(conn, OWNER)
    conn.execute(
        "UPDATE harness_sessions SET mode='parked',executor=%s,"
        "executor_surface=%s,executor_version=%s WHERE session_id=%s",
        (
            executor,
            surface,
            {
                "claude-code": "2.1.238",
                "codex": "0.148.0-alpha.15",
                "cursor": "2026.08.25-3e8eec8",
            }[executor],
            OWNER,
        ),
    )
    _claim(
        conn,
        session_id=OWNER,
        target_kind="item",
        scope_json=make_item_target(MEMBER).scope_json(),
    )
