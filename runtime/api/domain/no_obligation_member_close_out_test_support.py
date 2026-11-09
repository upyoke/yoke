# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
    _run,
)

from runtime.api.domain.deployment_qa_member_acceptance_notice_test_support import (
    _executing_run,
)

from runtime.api.domain.deployment_run_composition_freeze_test_support import (
    _environment,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _recipients,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.backlog_inserts import insert_qa_requirement

from yoke_core.domain.dash_execution import record_dash_evidence

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)

from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.post_deploy_verification_answer import (
    DECLARATION_QA_KIND,
    NO_OBLIGATION_QA_KIND,
)

from yoke_core.domain.schema_work_claim_sql import scope_int_sql


def _no_obligation(conn: Any, item_id: int, *, reason: str) -> None:
    insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind=NO_OBLIGATION_QA_KIND,
        qa_phase="post_deploy",
        blocking_mode="non_blocking",
        instructions=reason,
    )


def _declared_none(conn: Any, item_id: int) -> None:
    insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind=DECLARATION_QA_KIND,
        qa_phase="post_deploy",
        blocking_mode="non_blocking",
        waived_at=iso8601_now(),
        waiver_rationale="operator declined the check",
        waiver_source="owner",
    )


def _landing_evidence(conn: Any, item_id: int) -> None:
    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="Landed the member.",
        verification_summary="nothing observable once deployed",
        verification_status="passed",
        commit_sha="a" * 40,
        merge_sha="b" * 40,
        touched_files=["src/member.py"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="a" * 40,
    )


def _ready_member(conn: Any, item_id: int, holder: str) -> None:
    _member_at_release_wait(conn, item_id)
    _parked_owner(conn, holder, item_id)
    _landing_evidence(conn, item_id)
