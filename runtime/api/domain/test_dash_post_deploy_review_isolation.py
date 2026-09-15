"""post_deploy intake on Dash review must not block pre-merge transition."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
    _seed_selected_requirement_run,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
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


def test_manual_acceptance_is_not_satisfied_by_admitted_copy(tmp_path: Path):
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _insert_dash(conn, item_id=2313, status="reviewing-implementation")
            original = insert_qa_requirement(
                conn,
                item_id=2313,
                qa_kind="method_case",
                qa_phase="manual_acceptance",
                method_id="browser-inspection",
                workflow_transition_id=ITEM_POSTURE_VERIFICATION_TRANSITION,
            )
            insert_qa_requirement(
                conn,
                item_id=None,
                deployment_run_id="run-manual-copy",
                qa_kind="method_case",
                qa_phase="post_deploy",
                method_id="browser-inspection",
                plan_case_key=admitted_requirement_case_key(int(original["id"])),
                requirement_source="flow_derived",
                deployment_stage="member-qa",
                deployment_member_item_id=2313,
            )
            copy = conn.execute(
                "SELECT id FROM qa_requirements WHERE plan_case_key=%s",
                (admitted_requirement_case_key(int(original["id"])),),
            ).fetchone()
            insert_qa_run(conn, qa_requirement_id=int(copy[0]), verdict="pass")
        finally:
            conn.close()
        blocked = evaluate(
            item_id=2313,
            target_status="done",
            db_path=db_path,
        )
        assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"


def test_admitted_copy_pass_lets_done_accept_without_original_run(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    from runtime.api.domain.test_status_transition_preflight import (
        _isolate_status_effects,
    )

    _isolate_status_effects(monkeypatch)
    item_id = 2320
    _insert_dash(test_db, item_id=item_id, status="reviewing-implementation")
    original_id = _original_requirement(
        test_db, item_id=item_id, method_id="browser-inspection"
    )
    test_db.execute(
        "UPDATE qa_requirements SET workflow_transition_id=%s WHERE id=%s",
        (ITEM_POSTURE_VERIFICATION_TRANSITION, original_id),
    )
    test_db.commit()
    _seed_selected_requirement_run(
        test_db,
        run_id="run-admitted-dash-done",
        item_id=item_id,
        requirement_id=original_id,
    )
    created = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-admitted-dash-done",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    copy_id = int(created["created_requirement_ids"][0])
    record_dash_evidence(
        test_db,
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
    db_path = str(test_db.info.dsn)
    blocked = evaluate(
        item_id=item_id, target_status="done", db_path=db_path
    )
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"

    insert_qa_run(test_db, qa_requirement_id=copy_id, verdict="pass")
    original = test_db.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s",
        (original_id,),
    ).fetchone()
    original_runs = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
        (original_id,),
    ).fetchone()[0]
    copy = test_db.execute(
        "SELECT item_id, plan_case_key, execution_target_json "
        "FROM qa_requirements WHERE id=%s",
        (copy_id,),
    ).fetchone()
    assert original["waived_at"] is None
    assert int(original_runs) == 0
    assert copy["item_id"] is None
    assert copy["plan_case_key"] == admitted_requirement_case_key(original_id)
    target = json.loads(copy["execution_target_json"])
    assert target["deployment"]["release_lineage"] == "c" * 40
    assert evaluate(item_id=item_id, target_status="done", db_path=db_path) is None

    actor_id = str(
        test_db.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )
    outcome = handle_transition(
        FunctionCallRequest(
            function="lifecycle.transition.execute",
            actor=ActorContext(session_id="dash-session", actor_id=actor_id),
            target=TargetRef(kind="item", item_id=item_id, project_id="yoke"),
            payload={
                "source_status": "reviewing-implementation",
                "target_status": "done",
                "reason": "release QA copy passed; original intake unused",
            },
        )
    )
    assert outcome.primary_success is True, outcome.error
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()[0]
    original_runs = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
        (original_id,),
    ).fetchone()[0]
    waived = test_db.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s",
        (original_id,),
    ).fetchone()[0]
    assert status == "done"
    assert int(original_runs) == 0
    assert waived is None
