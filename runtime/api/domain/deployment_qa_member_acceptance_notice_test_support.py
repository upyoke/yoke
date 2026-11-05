# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    _member_at_release_wait,
    _parked_owner,
)

from runtime.api.domain.deployment_qa_run_acceptance_test_support import _settle

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.domain.deployment_qa_stage_ordering_test_support import (
    _stages as _run_scoped_stages,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _project,
    _recipients,
)

from yoke_core.domain import deployment_qa_member_acceptance_notice as notice

from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)

from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status


def _executing_run(
    conn: Any,
    run_id: str,
    members: tuple[int, ...],
    *,
    stages: list | None = None,
    plan_slug: str,
) -> None:
    _project(conn)
    for item_id in members:
        _member_at_release_wait(conn, item_id)
        _parked_owner(conn, HOLDER_A if item_id == members[0] else HOLDER_B, item_id)
    _seed_run(
        conn,
        run_id=run_id,
        stages=stages or _stages(_plan(conn, plan_slug)),
        members=(),
        existing_members=members,
    )
