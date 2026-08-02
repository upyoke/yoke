"""Real lifecycle authorities for selected Dash item posture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.dash_path_claim_posture import ensure_survey_path_claim
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_posture_bindings import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.workflow_status_transition_preflight import (
    prepare_status_transition,
)


@pytest.fixture
def dash_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        from yoke_core.domain.deployment_runs_schema import cmd_init

        cmd_init(db_path)
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "INSERT INTO actors "
                "(id, kind, system_component, created_at) "
                "VALUES (901, 'human', NULL, %s) ON CONFLICT DO NOTHING",
                (iso8601_now(),),
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


def _insert_dash(conn, *, item_id: int, posture: dict) -> None:
    insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status="idea",
        source="901",
        workflow_posture=json.dumps(posture),
    )


def _insert_session(conn, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat, actor_id) "
        "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s, 901)",
        (session_id, now, now),
    )
    conn.commit()


def test_selected_path_claims_register_activate_and_check_coverage(
    dash_db_path: str,
):
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(conn, item_id=2301, posture={"path_claims": True})
        _insert_session(conn, "dash-session")
        claim_id = ensure_survey_path_claim(
            conn,
            item_id=2301,
            session_id="dash-session",
            touch_paths=["ui/workflows.js"],
            integration_target="main",
        )
        assert claim_id is not None
        claim = conn.execute(
            "SELECT state FROM path_claims WHERE id=%s",
            (claim_id,),
        ).fetchone()
        assert claim[0] == "planned"
        declared = conn.execute(
            "SELECT pt.path_string FROM path_claim_targets pct "
            "JOIN path_targets pt ON pt.id=pct.target_id "
            "WHERE pct.claim_id=%s",
            (claim_id,),
        ).fetchall()
        assert [row[0] for row in declared] == ["ui/workflows.js"]
    finally:
        conn.close()
    blocked = evaluate(
        item_id=2301,
        target_status="implementing",
        db_path=dash_db_path,
    )
    assert blocked["error_code"] == "GATE_DASH_PATH_CLAIM_INACTIVE"
    conn = connect_test_db(dash_db_path)
    try:
        conn.execute(
            "UPDATE path_claims SET state='active', base_commit_sha=%s WHERE id=%s",
            ("a" * 40, claim_id),
        )
        conn.commit()
        record_dash_evidence(
            conn,
            item_id=2301,
            result_summary="Updated workflow composition.",
            verification_summary="Focused checks passed.",
            verification_status="passed",
            commit_sha="b" * 40,
            merge_sha="c" * 40,
            touched_files=["ui/other.js"],
            tree_root="/repo/.worktrees/lane",
            tree_head_sha="abc1234",
        )
    finally:
        conn.close()
    assert (
        evaluate(
            item_id=2301,
            target_status="implementing",
            db_path=dash_db_path,
        )
        is None
    )
    coverage = evaluate(
        item_id=2301,
        target_status="done",
        db_path=dash_db_path,
    )
    assert coverage["error_code"] == "GATE_DASH_PATH_CLAIM_COVERAGE"


def test_selected_ad_hoc_verification_requires_bound_passing_case(
    dash_db_path: str,
):
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(
            conn,
            item_id=2302,
            posture={
                "verification": {"kind": "ad_hoc", "method_id": "browser-check"},
            },
        )
        missing = evaluate(
            item_id=2302,
            target_status=ITEM_POSTURE_VERIFICATION_TRANSITION,
            db_path=dash_db_path,
        )
        assert missing["error_code"] == "GATE_DASH_VERIFICATION_REQUIRED"
        requirement = insert_qa_requirement(
            conn,
            item_id=2302,
            qa_kind="method_case",
            method_id="browser-check",
            workflow_transition_id=ITEM_POSTURE_VERIFICATION_TRANSITION,
        )
        requirement_id = int(requirement["id"])
    finally:
        conn.close()
    unsatisfied = evaluate(
        item_id=2302,
        target_status=ITEM_POSTURE_VERIFICATION_TRANSITION,
        db_path=dash_db_path,
    )
    assert unsatisfied["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"

    conn = connect_test_db(dash_db_path)
    try:
        insert_qa_run(conn, qa_requirement_id=requirement_id, verdict="pass")
    finally:
        conn.close()
    assert (
        evaluate(
            item_id=2302,
            target_status=ITEM_POSTURE_VERIFICATION_TRANSITION,
            db_path=dash_db_path,
        )
        is None
    )


def test_selected_plan_verification_requires_its_bound_passing_cases(
    dash_db_path: str,
):
    conn = connect_test_db(dash_db_path)
    try:
        plan_id = conn.execute(
            "INSERT INTO qa_plans "
            "(project_id, slug, name, created_at, updated_at) "
            "VALUES (1, 'dash-proof', 'Dash proof', %s, %s) RETURNING id",
            (iso8601_now(), iso8601_now()),
        ).fetchone()[0]
        _insert_dash(
            conn,
            item_id=2305,
            posture={
                "verification": {"kind": "plan", "plan_id": plan_id},
            },
        )
        requirement = insert_qa_requirement(
            conn,
            item_id=2305,
            plan_id=plan_id,
            qa_kind="plan_case",
            workflow_transition_id=ITEM_POSTURE_VERIFICATION_TRANSITION,
        )
        requirement_id = int(requirement["id"])
    finally:
        conn.close()

    blocked = evaluate(
        item_id=2305,
        target_status=ITEM_POSTURE_VERIFICATION_TRANSITION,
        db_path=dash_db_path,
    )
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    conn = connect_test_db(dash_db_path)
    try:
        insert_qa_run(conn, qa_requirement_id=requirement_id, verdict="pass")
    finally:
        conn.close()
    assert (
        evaluate(
            item_id=2305,
            target_status=ITEM_POSTURE_VERIFICATION_TRANSITION,
            db_path=dash_db_path,
        )
        is None
    )


def test_approval_on_done_creates_and_requires_project_owner_request(
    dash_db_path: str,
):
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(conn, item_id=2303, posture={"approval_on_done": True})
    finally:
        conn.close()
    conn = connect_test_db(dash_db_path)
    try:
        preflight = prepare_status_transition(
            conn,
            item_id=2303,
            target_status="done",
            originator_actor_id=901,
            session_id="dash-session",
        )
    finally:
        conn.close()
    assert preflight.failure is not None
    assert preflight.failure["error_code"] == "GATE_APPROVAL_REQUIRED"

    conn = connect_test_db(dash_db_path)
    try:
        decision = conn.execute(
            "SELECT id FROM decision_requests "
            "WHERE subject_type='item_transition' "
            "AND subject_key='2303:done'",
        ).fetchone()
        authorities = conn.execute(
            "SELECT role_name FROM decision_request_role_authorities "
            "WHERE request_id=%s",
            (decision[0],),
        ).fetchall()
    finally:
        conn.close()
    assert [row[0] for row in authorities] == ["owner"]
    gate = evaluate(
        item_id=2303,
        target_status="done",
        db_path=dash_db_path,
    )
    assert gate["error_code"] == "GATE_DASH_APPROVAL_REQUIRED"


def test_deploy_posture_requires_successful_item_bound_merge_lineage(
    dash_db_path: str,
):
    merge_sha = "d" * 40
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(conn, item_id=2304, posture={"deployment": True})
        record_dash_evidence(
            conn,
            item_id=2304,
            result_summary="Merged the Dash.",
            verification_summary="Focused checks passed.",
            verification_status="passed",
            commit_sha="e" * 40,
            merge_sha=merge_sha,
            touched_files=["ui/dash.js"],
            tree_root="/repo/.worktrees/lane",
            tree_head_sha="abc1234",
        )
        insert_deployment_run(
            conn,
            id="run-dash-2304",
            status="succeeded",
            current_stage="complete",
            release_lineage="f" * 40,
            completed_at=iso8601_now(),
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s, %s, %s)",
            ("run-dash-2304", 2304, iso8601_now()),
        )
        conn.commit()
    finally:
        conn.close()

    mismatch = evaluate(
        item_id=2304,
        target_status="done",
        db_path=dash_db_path,
    )
    assert mismatch["error_code"] == "GATE_DASH_DEPLOYMENT_LINEAGE"
    conn = connect_test_db(dash_db_path)
    try:
        conn.execute(
            "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s",
            (merge_sha, "run-dash-2304"),
        )
        conn.commit()
    finally:
        conn.close()
    assert (
        evaluate(
            item_id=2304,
            target_status="done",
            db_path=dash_db_path,
        )
        is None
    )
