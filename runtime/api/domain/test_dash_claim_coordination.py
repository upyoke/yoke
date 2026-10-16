"""Dash overlap attestation, recovery and posture amendment behavior."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.domain._path_claims_test_helpers import seed_target, seed_claim
from runtime.api.domain.test_item_posture_amend import _dash, _stored
from yoke_core.domain.item_dependency import cmd_dependency_add
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.path_claims_overlap import classify_overlap, OverlapClassification
from yoke_core.domain.path_claim_coordination_decision import _suggested_commands
from yoke_core.domain.path_claims_overlap_survey import SURVEY_ADVISORY_YIELD
from yoke_core.domain.work_claim_targets import make_item_target


def _hold_as(conn, item_id: int, mode: str) -> None:
    """Give the item a live exclusive holder whose session mode is the source."""
    session_id = f"holder-{item_id}"
    stamp = "2026-10-16T00:00:00Z"
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "execution_level, workspace, project_id, mode, offered_at, last_heartbeat) "
        "VALUES (%s, 'claude-code', 'anthropic', 'claude-opus-5-5', 'primary', "
        "'/tmp/dash-holder', 1, %s, %s, %s)",
        (session_id, mode, stamp, stamp),
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claim_type, "
        "claimed_at, last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
        (session_id, make_item_target(item_id).scope_json(), stamp, stamp),
    )


def test_dash_attestation_removes_only_the_independent_overlap():
    with test_database() as conn:
        candidate = _dash(conn, item_id=2810, posture={"path_claims": True})
        holder = _dash(conn, item_id=2811, posture={"path_claims": True})
        target = seed_target(conn, path_string="shared.py")
        claim = seed_claim(conn, item_id=holder, target_id=target, state="active")
        args = dict(
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=candidate,
        )
        assert classify_overlap(conn, **args) is OverlapClassification.INCOMPATIBLE
        _hold_as(conn, candidate, "dash")
        commands = _suggested_commands(conn, candidate, holder, ["shared.py"], claim)
        command = next(c for c in commands if "--gate-point coordination_only" in c)
        assert " dash --gate-point coordination_only" in command
        cmd_dependency_add(
            conn,
            "YOK-2810",
            "YOK-2811",
            "dash",
            gate_point="coordination_only",
            rationale=f"decision=coordination_only. shared_paths=shared.py. "
            f"conflicting_claim_id={claim}. independence_evidence="
            "candidate edits recovery, holder edits rendering; no coupling",
        )
        assert classify_overlap(conn, **args) is OverlapClassification.NONE
        assert _stored(conn, candidate) == {"path_claims": True}


@pytest.mark.parametrize("status", ["idea", "implementing", "reviewing-implementation"])
def test_mistaken_claim_selection_can_be_cleared_after_filing(status):
    with test_database() as conn:
        item = _dash(conn, item_id=2812, posture={"path_claims": True}, status=status)
        result = amend_item_posture(
            conn,
            item_id=item,
            key="path_claims",
            clear=True,
            reason="selected by mistake",
        )
        assert result["changed"] is True
        assert _stored(conn, item) == {}
        again = amend_item_posture(
            conn, item_id=item, key="path_claims", clear=True, reason="same selection"
        )
        assert again["changed"] is False


def test_survey_contact_does_not_teach_releasing_on_a_shared_filename():
    assert "order-dependent" in SURVEY_ADVISORY_YIELD
    assert "advisory" in SURVEY_ADVISORY_YIELD
    assert "release the work claim" not in SURVEY_ADVISORY_YIELD


def test_dash_directional_attestation_uses_the_same_review_as_refine():
    from yoke_core.domain.path_claim_hard_block_review import review_activation_row

    result = review_activation_row(
        source="dash",
        gate_point="activation",
        rationale="shared_paths=shared.py; no ordering evidence",
    )
    assert result.over_hard
