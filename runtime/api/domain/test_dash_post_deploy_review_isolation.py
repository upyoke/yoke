"""post_deploy intake on Dash review must not block pre-merge transition."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)


POSTURE = {"verification": {"kind": "ad_hoc", "method_id": "browser-inspection"}}


def _insert_dash(conn, *, item_id: int, status: str) -> None:
    insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status=status,
        workflow_posture=json.dumps(POSTURE),
    )


def _insert_post_deploy(conn, *, item_id: int):
    return insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind="method_case",
        qa_phase="post_deploy",
        method_id="browser-inspection",
        target_env="stage",
        workflow_transition_id=ITEM_POSTURE_VERIFICATION_TRANSITION,
        success_policy="screenshot on ENV",
    )


def test_post_deploy_review_row_does_not_block_review_gate(tmp_path: Path):
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _insert_dash(conn, item_id=2310, status="implementing")
            _insert_post_deploy(conn, item_id=2310)
        finally:
            conn.close()
        assert (
            evaluate(
                item_id=2310,
                target_status=ITEM_POSTURE_VERIFICATION_TRANSITION,
                db_path=db_path,
            )
            is None
        )
        blocked = evaluate(
            item_id=2310,
            target_status="done",
            db_path=db_path,
        )
        assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"


def test_unsatisfied_verification_still_blocks_review(tmp_path: Path):
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _insert_dash(conn, item_id=2311, status="implementing")
            insert_qa_requirement(
                conn,
                item_id=2311,
                qa_kind="method_case",
                qa_phase="verification",
                method_id="browser-inspection",
                workflow_transition_id=ITEM_POSTURE_VERIFICATION_TRANSITION,
            )
        finally:
            conn.close()
        blocked = evaluate(
            item_id=2311,
            target_status=ITEM_POSTURE_VERIFICATION_TRANSITION,
            db_path=db_path,
        )
        assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"


def test_lifecycle_transition_records_post_deploy_without_waiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from runtime.api.backlog_mutations_test_helpers import _patch_externals

    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "INSERT INTO actors "
                "(id, kind, system_component, created_at) "
                "VALUES (901, 'human', NULL, %s) ON CONFLICT DO NOTHING",
                (iso8601_now(),),
            )
            conn.commit()
            _insert_dash(conn, item_id=2312, status="implementing")
            _insert_post_deploy(conn, item_id=2312)
        finally:
            conn.close()
        with _patch_externals(), mock.patch.dict(
            os.environ,
            {"YOKE_DB": db_path, "YOKE_CLAIM_BYPASS": "test-bypass"},
        ):
            outcome = handle_transition(
                FunctionCallRequest(
                    function="lifecycle.transition.execute",
                    actor=ActorContext(session_id="dash-session", actor_id="901"),
                    target=TargetRef(kind="item", item_id=2312, project_id="yoke"),
                    payload={
                        "source_status": "implementing",
                        "target_status": "reviewing-implementation",
                        "reason": "implementation complete; ready for review",
                    },
                )
            )
        assert outcome.primary_success is True, outcome.error
        conn = connect_test_db(db_path)
        try:
            status = conn.execute(
                "SELECT status FROM items WHERE id = %s",
                (2312,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert status == "reviewing-implementation"
        later = evaluate(
            item_id=2312,
            target_status="done",
            db_path=db_path,
        )
        assert later["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
