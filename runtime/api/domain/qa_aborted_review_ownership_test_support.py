# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)

from runtime.api.domain.qa_capture_pending_review_test_support import (
    MEMBER,
    _acceptance,
    _seed_pending,
)

from yoke_core.domain.deployment_qa_stage_acceptance import STAGE_AWAITING_REVIEW

from yoke_core.domain.qa_deployment_run_settlement import (
    restore_retry_obligations,
    settle_unsuccessful_run,
)

from yoke_core.domain.qa_pending_agent_review import (
    pending_review_for_requirement,
    pending_review_requirements,
)

from yoke_core.domain.qa_plan_settled_review import (
    withdraw_settled_agent_review_wakes,
)

from yoke_core.domain.work_claim_targets import make_item_target

OWNER = "capture-session"


def _fail_run(conn, execution):
    """The incident's stop: the run fails mid-capture, then is retried."""
    run_id = execution["deployment_run_id"]
    settle_unsuccessful_run(conn, run_id, reason=f"deployment run {run_id} failed")
    restore_retry_obligations(conn, run_id)
    conn.commit()
