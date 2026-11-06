# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.domain.dash_post_deploy_done_consumption_test_support import (
    _accept_member_qa,
    _bind_original,
    _retarget_run,
    _transition_done,
)

from runtime.api.domain.dash_post_deploy_review_isolation_test_support import (
    _insert_dash,
)

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _seed_selected_requirement_run,
)

from runtime.api.fixtures.backlog_inserts import insert_qa_run

from yoke_core.domain import delivery_evidence_ladder as ladder

from yoke_core.domain.dash_execution import record_dash_evidence

from yoke_core.domain.dash_posture_gate import evaluate

from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed

from yoke_core.domain.delivery_evidence_ladder import delivery_evidence

from yoke_core.domain.item_merge_receipt_document import record_entry

from yoke_core.domain.qa_gates import GateTarget, check_done_gate


def _record_evidence(conn, *, item_id: int) -> None:
    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="Merged the Dash.",
        verification_summary="Focused checks passed.",
        verification_status="passed",
        commit_sha="e" * 40,
        merge_sha="d" * 40,
        touched_files=["ui/dash.js"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="abc1234",
    )
