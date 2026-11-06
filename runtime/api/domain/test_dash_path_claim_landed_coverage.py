# ruff: noqa: F811
"""Dash done gate reads the coverage that landing released."""

from __future__ import annotations

from runtime.api.domain.dash_posture_deployment_containment_test_support import (dash_db_path as dash_db_path)

from runtime.api.domain.dash_posture_gate_test_support import (
    _insert_dash,
    _insert_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.item_landings import ItemLanding, append_landing
from yoke_core.domain.path_claims_landing import release_landed_claims
from yoke_core.domain.path_claims_register import register_for_item


def _land(conn, item_id: int) -> None:
    append_landing(
        conn,
        ItemLanding(
            item_id=item_id,
            merge_sha="c" * 40,
            candidate_sha="b" * 40,
            target_branch="main",
            route="standalone",
            landed_at=utc_now(),
        ),
    )
    conn.commit()


def _record_evidence(conn, item_id: int, touched: list[str]) -> None:
    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="Updated workflow composition.",
        verification_summary="Focused checks passed.",
        verification_status="passed",
        commit_sha="b" * 40,
        merge_sha="c" * 40,
        touched_files=touched,
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="abc1234",
    )


def _landed_item(db_path: str, item_id: int, touched: list[str]) -> None:
    conn = connect_test_db(db_path)
    try:
        _insert_dash(
            conn, item_id=item_id, posture={"path_claims": True}, status="release"
        )
        _insert_session(conn, f"dash-session-{item_id}")
        claim_id = register_for_item(
            conn,
            item_id=item_id,
            session_id=f"dash-session-{item_id}",
            paths=["ui/workflows.js"],
            integration_target="main",
            allow_planned=True,
        )
        conn.execute(
            "UPDATE path_claims SET state='active', base_commit_sha=%s WHERE id=%s",
            ("a" * 40, claim_id),
        )
        conn.commit()
        _land(conn, item_id)
        assert release_landed_claims(conn, item_id=item_id) == [claim_id]
        conn.commit()
        _record_evidence(conn, item_id, touched)
    finally:
        conn.close()


def test_done_accepts_coverage_released_at_landing(dash_db_path: str):
    _landed_item(dash_db_path, 2401, ["ui/workflows.js"])
    assert evaluate(item_id=2401, target_status="done", db_path=dash_db_path) is None


def test_done_refuses_touched_file_outside_landed_coverage(dash_db_path: str):
    _landed_item(dash_db_path, 2402, ["ui/workflows.js", "ui/other.js"])
    gate = evaluate(item_id=2402, target_status="done", db_path=dash_db_path)
    assert gate["error_code"] == "GATE_DASH_PATH_CLAIM_COVERAGE"
    assert "released at landing: ui/other.js" in gate["error"]


def test_done_refuses_without_open_or_landed_coverage(dash_db_path: str):
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(
            conn, item_id=2403, posture={"path_claims": True}, status="release"
        )
        _land(conn, 2403)
        _record_evidence(conn, 2403, ["ui/workflows.js"])
    finally:
        conn.close()
    gate = evaluate(item_id=2403, target_status="done", db_path=dash_db_path)
    assert gate["error_code"] == "GATE_DASH_PATH_CLAIM_REQUIRED"
    assert "no claim released at the current landing" in gate["error"]
