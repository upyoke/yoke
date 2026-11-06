# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import contextmanager

from unittest.mock import patch

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    QaCasesNotSelectedError,
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_member_plans import member_plan_ids

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.deployment_qa_plan_groups import run_groups

from yoke_core.domain.handlers import qa_post_deploy_record_no_obligation as record

from yoke_core.domain.post_deploy_verification_answer import (
    ANSWERED,
    UNANSWERED,
    answer_for_item,
    classify,
)

from yoke_core.domain.qa_plan_management import QaPlanError

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

RETRACT_REASON = (
    "attached a machine-local CLI probe as standing post-deploy verification"
)


def _attach_post_deploy(conn, *, item_id: int, slug: str) -> int:
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

    plan_id = create_smoke_plan(conn, project="yoke", slug=slug)
    attach_plan_to_item(
        conn,
        plan_id=int(plan_id),
        item_id=item_id,
        transition_id="release",
        qa_phase="post_deploy",
    )
    return int(plan_id)


def _materialize_item(conn, *, item_id: int) -> dict:
    from yoke_core.domain.qa_plan_attachments import materialize_for_item

    return materialize_for_item(conn, item_id=item_id, transition_id="release")


def _retract(conn, *, item_id: int, plan_id: int, reason: str = RETRACT_REASON):
    from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item

    return retract_plan_from_item(
        conn,
        item_id=item_id,
        plan_id=int(plan_id),
        transition_id="release",
        reason=reason,
        source="operator",
    )
