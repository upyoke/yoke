"""Real lifecycle authorities for selected Dash item posture."""

from __future__ import annotations

from runtime.api.domain.dash_posture_gate_test_support import (
    _insert_dash as _insert_dash,
    _insert_session as _insert_session,
)
from runtime.api.domain.dash_posture_deployment_containment_test_support import (
    dash_db_path as dash_db_path,
)


from runtime.api.fixtures.backlog_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.path_claims_register import register_for_item
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.workflow_status_transition_preflight import (
    prepare_status_transition,
)


def test_selected_path_claims_register_activate_and_check_coverage(
    dash_db_path: str,
):
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(conn, item_id=2301, posture={"path_claims": True})
        _insert_session(conn, "dash-session")
        claim_id = register_for_item(
            conn,
            item_id=2301,
            session_id="dash-session",
            paths=["ui/workflows.js"],
            integration_target="main",
            allow_planned=True,
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
        # "done" is declared from "release", the pinned canon's own wait.
        _insert_dash(
            conn,
            item_id=2303,
            posture={"approval_on_done": True},
            status="release",
        )
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
            "SELECT r.role_name FROM audience_rules r JOIN decision_requests d ON d.audience_id=r.audience_id "
            "WHERE d.id=%s AND r.role_name IS NOT NULL",
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


def test_approval_on_done_explains_when_no_human_owner_remains(
    dash_db_path: str,
):
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(
            conn,
            item_id=2306,
            posture={"approval_on_done": True},
            status="release",
        )
        prepare_status_transition(
            conn,
            item_id=2306,
            target_status="done",
            originator_actor_id=901,
            session_id="dash-session",
        )
        conn.execute(
            "UPDATE actors SET status = 'disabled' WHERE kind = 'human' AND id IN ("
            "SELECT apr.actor_id FROM actor_project_roles apr "
            "JOIN roles r ON r.id = apr.role_id "
            "WHERE r.name = 'owner')"
        )
        conn.commit()
    finally:
        conn.close()
    gate = evaluate(item_id=2306, target_status="done", db_path=dash_db_path)
    assert gate["error_code"] == "empty_audience_members"
    assert "no active person" in gate["error"]
    assert "--audience <name>" in gate["remediation_hint"]
