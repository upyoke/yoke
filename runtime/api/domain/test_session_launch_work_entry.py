"""Acknowledged item launches must claim their assignment before the deadline."""

import json

import pytest

from yoke_core.domain.session_launch_assignment import refuse_held_assigned_item
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import report_launch_attempt
from yoke_core.domain.session_launch_registration import complete_launch_for_message
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.domain.session_launch_test_support import add_relay, launch_connection
from runtime.api.domain.session_launch_attested_binding_test_support import (
    bind,
    registered_launch,
)
from runtime.api.domain.session_launch_terminal_admission_test_support import (
    _seed_pinned_item,
)


def setup_launch(*, acknowledge=True, bind_hook=True):
    conn = launch_connection()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN offered_at TEXT")
    ref = _seed_pinned_item(conn, status="idea")
    add_relay(conn)
    launch, claim, session = registered_launch(conn, "codex-cli", "assignment")
    conn.execute(
        "UPDATE session_launches SET item_id=? WHERE launch_id=?",
        (41, launch.launch_id),
    )
    conn.commit()
    if bind_hook:
        bind(conn, launch, claim, session)
        if acknowledge:
            conn.execute(
                "UPDATE session_message_recipients SET state='acknowledged' WHERE message_id=?",
                (launch.message_id,),
            )
            conn.commit()
    return conn, ref, launch, claim, session


def claim_item(conn, session, *, item_id=41, released=False, at="2026-08-22T12:00:03Z"):
    conn.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,released_at) VALUES (?,'item',?,?,?)",
        (session, make_item_target(item_id).scope_json(), at, at if released else None),
    )
    conn.commit()


def test_acknowledgement_waits_for_own_item_claim_and_sweep_closes_after_entry():
    conn, _ref, launch, _claim, session = setup_launch()
    pending = complete_launch_for_message(
        conn,
        message_id=launch.message_id,
        session_id=session,
        now="2026-08-22T12:00:03Z",
    )
    assert pending.state == "awaiting_registration"
    assert pending.result_code == "launch_work_claim_pending"
    claim_item(conn, session)
    settled = settle_launch_deadlines(conn, now="2026-08-22T12:00:04Z")
    assert settled[0].state == "succeeded"


@pytest.mark.parametrize("claimed_item", (None, 42))
def test_missing_or_wrong_item_claim_fails_and_releases_launch_only_worker(
    claimed_item,
):
    conn, ref, launch, _claim, session = setup_launch()
    if claimed_item:
        claim_item(conn, session, item_id=claimed_item)
    settle_launch_deadlines(conn, now="2026-08-22T12:10:01Z")
    failed = get_launch(conn, launch.launch_id)
    assert failed.state == "failed"
    assert failed.result_code == "launch_work_claim_missing"
    assert "retry" in json.loads(failed.result_evidence)["recovery"]
    # The session itself stays live, but this failed launch no longer staffs its item.
    refuse_held_assigned_item(conn, public_ref=ref, project_id=10)


def test_released_assignment_claim_proves_entry_and_late_claim_does_not():
    conn, _ref, launch, _claim, session = setup_launch()
    claim_item(conn, session, released=True)
    assert (
        settle_launch_deadlines(conn, now="2026-08-22T12:10:01Z")[0].state
        == "succeeded"
    )
    conn, _ref, launch, _claim, session = setup_launch()
    claim_item(conn, session, at="2026-08-22T12:10:01Z")
    assert (
        settle_launch_deadlines(conn, now="2026-08-22T12:10:02Z")[0].result_code
        == "launch_work_claim_missing"
    )


def test_a_real_assignment_holder_still_blocks_restaffing():
    conn, ref, launch, _claim, session = setup_launch()
    claim_item(conn, session)
    conn.execute(
        "UPDATE session_launches SET state='failed' WHERE launch_id=?",
        (launch.launch_id,),
    )
    conn.commit()
    with pytest.raises(SessionLaunchError) as refused:
        refuse_held_assigned_item(conn, public_ref=ref, project_id=10)
    assert refused.value.code == "item_has_live_worker"


def test_uncertain_unbound_launch_expires_and_does_not_staff_the_item_forever():
    conn, ref, launch, claim, _session = setup_launch(bind_hook=False)
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="outcome_unknown",
        now="2026-08-22T12:00:03Z",
    )
    settle_launch_deadlines(conn, now="2026-08-22T12:10:01Z")
    assert get_launch(conn, launch.launch_id).state == "expired"
    refuse_held_assigned_item(conn, public_ref=ref, project_id=10)
