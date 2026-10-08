"""Dash review and close-out grade the corrected case, preserving failed history."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_dash_posture_gate import (
    _insert_dash,
    dash_db_path as dash_db_path,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_item_worktree,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.qa_gate_definitions import GateTarget, LatestCodeRef
from yoke_core.domain.qa_gate_helpers import _resolve_latest_code_ref
from yoke_core.domain.qa_requirement_replacement import (
    discharge_declared_replacements,
    point_at_replacement,
)
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)

ITEM_ID = 2307
CANDIDATE_DIGEST = "candidate-target"
CANDIDATE_SHA = "a" * 40


def _cases(conn):
    _insert_dash(
        conn,
        item_id=ITEM_ID,
        posture={"verification": {"kind": "ad_hoc", "method_id": "command"}},
    )
    common = {
        "item_id": ITEM_ID,
        "qa_kind": "method_case",
        "workflow_transition_id": ITEM_POSTURE_VERIFICATION_TRANSITION,
        "execution_target_digest": CANDIDATE_DIGEST,
    }
    original = int(insert_qa_requirement(conn, method_id="command", **common)["id"])
    # A corrected plan/method need not match the posture selector. Its declared
    # same-scope supersession still needs independent evidence at this gate.
    replacement = int(
        insert_qa_requirement(conn, method_id="command-ci", **common)["id"]
    )
    insert_qa_run(conn, qa_requirement_id=original, verdict="fail")
    point_at_replacement(conn, original, replacement)
    conn.commit()
    return original, replacement


def _verdict(
    conn, requirement_id, verdict="pass", digest=CANDIDATE_DIGEST, sha=CANDIDATE_SHA
):
    insert_qa_run(
        conn,
        qa_requirement_id=requirement_id,
        performed_by="agent",
        verdict=verdict,
        verdict_reason="Evidence needs review" if verdict == "undetermined" else None,
        raw_result=json.dumps(
            {
                "execution_target_digest": digest,
                "verification_tree": {"head_sha": sha},
            }
        ),
    )
    if verdict == "pass":
        discharge_declared_replacements(conn, [requirement_id])
        conn.commit()


def _gate(db_path, transition=ITEM_POSTURE_VERIFICATION_TRANSITION):
    return evaluate(item_id=ITEM_ID, target_status=transition, db_path=db_path)


def test_passing_declared_replacement_clears_review_without_waiver(dash_db_path):
    conn = connect_test_db(dash_db_path)
    try:
        original, replacement = _cases(conn)
        _verdict(conn, replacement)
        row = conn.execute(
            "SELECT waived_at, superseded_by_requirement_id FROM qa_requirements WHERE id=%s",
            (original,),
        ).fetchone()
        assert row["waived_at"] is None
        assert row["superseded_by_requirement_id"] == replacement
    finally:
        conn.close()
    assert _gate(dash_db_path) is None


@pytest.mark.parametrize(
    "state",
    ["missing", "fail", "undetermined", "other_candidate", "stale_pass", "other_scope"],
)
def test_unproven_replacement_still_blocks_and_names_the_case(dash_db_path, state):
    conn = connect_test_db(dash_db_path)
    try:
        _, replacement = _cases(conn)
        if state in {"other_candidate", "stale_pass", "other_scope"}:
            if state == "other_candidate":
                _verdict(conn, replacement, digest="another-candidate")
            elif state == "other_scope":
                _verdict(conn, replacement)
                conn.execute(
                    "UPDATE qa_requirements SET execution_target_digest=%s WHERE id=%s",
                    ("another-candidate", replacement),
                )
            else:
                _verdict(conn, replacement)
                _verdict(conn, replacement, "fail")
            conn.commit()
        elif state != "missing":
            _verdict(conn, replacement, state)
    finally:
        conn.close()
    blocked = _gate(dash_db_path)
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    assert f"replacement #{replacement}" in blocked["error"]
    assert "independent verdict" in blocked["remediation_hint"]
    assert "same candidate" in blocked["remediation_hint"]


def test_original_without_replacement_keeps_its_own_pass_rule(dash_db_path):
    conn = connect_test_db(dash_db_path)
    try:
        original, _ = _cases(conn)
        conn.execute(
            "UPDATE qa_requirements SET replacement_requirement_id=NULL WHERE id=%s",
            (original,),
        )
        conn.commit()
        assert _gate(dash_db_path)["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
        _verdict(conn, original)
    finally:
        conn.close()
    assert _gate(dash_db_path) is None


def test_same_settlement_clears_selected_verification_at_done(dash_db_path):
    from yoke_core.domain.dash_posture_verification_gate import verification_gate

    conn = connect_test_db(dash_db_path)
    try:
        _, replacement = _cases(conn)
        _verdict(conn, replacement)
        assert (
            verification_gate(
                conn,
                item_id=ITEM_ID,
                verification={"kind": "ad_hoc", "method_id": "command"},
                target_status="done",
            )
            is None
        )
    finally:
        conn.close()


@pytest.mark.parametrize("sha", [CANDIDATE_SHA, "b" * 40, ""])
def test_premerge_replacement_proves_exact_lane_commit(dash_db_path, monkeypatch, sha):
    monkeypatch.setenv("YOKE_QA_GATE_COMMIT_SHA", CANDIDATE_SHA)
    conn = connect_test_db(dash_db_path)
    try:
        _, replacement = _cases(conn)
        _verdict(conn, replacement, sha=sha)
    finally:
        conn.close()
    result = _gate(dash_db_path)
    if sha == CANDIDATE_SHA:
        assert result is None
    else:
        assert result["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
        assert f"replacement #{replacement}" in result["error"]


@pytest.mark.parametrize("sha", [CANDIDATE_SHA, "c" * 40, ""])
def test_checkout_free_replacement_after_merge_proves_accepted_lane_head(
    dash_db_path, monkeypatch, sha
):
    previous_merge = "b" * 40
    monkeypatch.setattr(
        "yoke_core.domain.qa_gate_helpers._git_latest_code_ref",
        lambda *args: LatestCodeRef(branch="corrected-lane"),
    )
    conn = connect_test_db(dash_db_path)
    try:
        _, replacement = _cases(conn)
        record_dash_evidence(
            conn,
            item_id=ITEM_ID,
            result_summary="Previous change merged.",
            verification_summary="Previous checks passed.",
            verification_status="passed",
            commit_sha=previous_merge,
            merge_sha=previous_merge,
            touched_files=["app.py"],
            tree_root="/repo/.worktrees/previous-lane",
            tree_head_sha=previous_merge,
        )
        lane = insert_item_worktree(conn, item_id=ITEM_ID, branch="corrected-lane")
        conn.execute(
            "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s",
            (CANDIDATE_SHA, lane["id"]),
        )
        conn.commit()
        _verdict(conn, replacement, sha=sha)
    finally:
        conn.close()
    latest = _resolve_latest_code_ref(GateTarget(item_id=ITEM_ID), dash_db_path)
    assert latest.sha == previous_merge
    assert latest.accepted_shas == (previous_merge, CANDIDATE_SHA)
    result = _gate(dash_db_path)
    if sha == CANDIDATE_SHA:
        assert result is None
    else:
        assert result["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
        assert f"replacement #{replacement}" in result["error"]


def test_declared_pending_successor_blocks_before_automatic_discharge(dash_db_path):
    conn = connect_test_db(dash_db_path)
    try:
        original, replacement = _cases(conn)
        assert (
            conn.execute(
                "SELECT superseded_by_requirement_id FROM qa_requirements WHERE id=%s",
                (original,),
            ).fetchone()[0]
            is None
        )
    finally:
        conn.close()
    result = _gate(dash_db_path)
    assert result["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    assert f"replacement #{replacement}" in result["error"]
