# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
    _run,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    _bodies,
    _recipients,
)

from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _no_obligation,
    _ready_member,
)

from runtime.api.domain.run_success_member_settlement_test_support import _executing_run

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.backlog_inserts import insert_qa_requirement, insert_qa_run

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)

from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member


def _waived_item_requirement(conn: Any, item_id: int) -> None:
    """An ordinary item check waived before release admission copies cases."""
    insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind="plan_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
        waived_at=iso8601_now(),
        waiver_rationale="operator accepted the waiver before release",
        waiver_source="owner",
    )


def _settled_member_requirement(
    conn: Any, *, item_id: int, run_id: str, resolution: str
) -> None:
    requirement = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        deployment_member_item_id=item_id,
        deployment_stage="item-qa",
        qa_kind="plan_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
        **(
            {
                "waived_at": iso8601_now(),
                "waiver_rationale": "operator accepted the waiver",
                "waiver_source": "owner",
            }
            if resolution == "waive"
            else {}
        ),
    )
    if resolution == "pass":
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            qa_kind="plan_case",
            verdict="pass",
        )
