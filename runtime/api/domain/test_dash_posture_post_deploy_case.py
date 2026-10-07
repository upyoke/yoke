"""A Dash posture case bound to the release stage binds the selected verification.

A change visible only once deployed selects a ``post_deploy`` Browser case on
its environment, bound to the release stage. Pre-merge review accepts that
case as the selected one; done still waits for the completion run's admitted
copy of it.
"""

from __future__ import annotations

import json

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.dash_posture_verification_gate import verification_gate

_POSTURE = {"verification": {"kind": "ad_hoc", "method_id": "browser-inspection"}}


def _insert_case(conn, item_id: int, *, qa_phase: str, transition: str) -> None:
    conn.execute(
        "INSERT INTO qa_requirements "
        "(item_id, method_id, runner_id, qa_kind, qa_phase, target_env, "
        " blocking_mode, workflow_transition_id, plan_id, "
        " instructions, expected_outcome, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            item_id,
            "browser-inspection",
            "browser_substrate",
            "plan_case",
            qa_phase,
            "production" if qa_phase == "post_deploy" else None,
            "blocking",
            transition,
            None,
            "Capture the changed screen on its environment.",
            "The screenshot shows the requested behavior.",
            "2026-01-01T00:00:00Z",
        ),
    )


def _gate(db_path: str, item_id: int, *, qa_phase: str, transition: str, target: str):
    conn = _conn(db_path)
    try:
        insert_item(
            conn,
            id=item_id,
            status="implementing",
            workflow_id="dash",
            workflow_posture=json.dumps(_POSTURE),
        )
        _insert_case(conn, item_id, qa_phase=qa_phase, transition=transition)
        conn.commit()
        return verification_gate(
            conn,
            item_id=item_id,
            verification=_POSTURE["verification"],
            target_status=target,
        )
    finally:
        conn.close()


def test_release_bound_post_deploy_case_binds_the_posture_before_merge(
    tmp_db,  # noqa: F811
) -> None:
    refusal = _gate(
        tmp_db,
        2431,
        qa_phase="post_deploy",
        transition="release",
        target="reviewing-implementation",
    )
    assert refusal is None, refusal


def test_release_bound_post_deploy_case_still_blocks_done_until_delivered(
    tmp_db,  # noqa: F811
) -> None:
    refusal = _gate(
        tmp_db,
        2432,
        qa_phase="post_deploy",
        transition="release",
        target="done",
    )
    assert refusal is not None
    assert "GATE_DASH_VERIFICATION_UNSATISFIED" in json.dumps(refusal)


def test_unbound_posture_refusal_teaches_both_placements(
    tmp_db,  # noqa: F811
) -> None:
    conn = _conn(tmp_db)
    try:
        insert_item(
            conn,
            id=2433,
            status="implementing",
            workflow_id="dash",
            workflow_posture=json.dumps(_POSTURE),
        )
        conn.commit()
        refusal = verification_gate(
            conn,
            item_id=2433,
            verification=_POSTURE["verification"],
            target_status="reviewing-implementation",
        )
    finally:
        conn.close()

    text = json.dumps(refusal)
    assert "GATE_DASH_VERIFICATION_REQUIRED" in text
    assert "post_deploy case with --target-env bound to the release stage" in text
