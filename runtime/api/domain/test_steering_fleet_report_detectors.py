"""The failures that arrive as silence, and the guesses not made about them."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    quiet_holder,
    seed_session,
)
from yoke_core.domain.steering_fleet_report_detectors import (
    landed_without_closeout,
    suspected_orphaned_waiters,
    unregistered_launches,
)


def _send(conn, message_id: str, *, sender: str, to: str, at: str, state="pending"):
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'a question', 'sha', %s, %s, %s)",
        (message_id, ACTOR_ID, sender, json.dumps({}), at, NOW),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id, session_id, project_id, resolution_evidence, "
        "routing_snapshot, state, created_at, wake_after, injection_count) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)",
        (message_id, to, PROJECT_ID, json.dumps({}), json.dumps({}), state, at, at),
    )


def _launch(
    conn,
    launch_id: str,
    *,
    deadline: str,
    state="awaiting_registration",
    result_code=None,
    native_session_id=None,
):
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'launch instruction', 'sha', %s, %s, %s)",
        (f"msg-{launch_id}", ACTOR_ID, ASKER, json.dumps({}), LONG_AGO, NOW),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, "
        "selected_surface, allow_surface_fallback, message_id, state, "
        "deadline_at, created_at, origin, assigned_machine_id, result_code, "
        "native_session_id) "
        "VALUES (%s, %s, %s, 'codex-cli', 'codex-cli', 0, %s, %s, %s, %s, "
        "'operator', 'machine-1', %s, %s)",
        (
            launch_id,
            ACTOR_ID,
            PROJECT_ID,
            f"msg-{launch_id}",
            state,
            deadline,
            LONG_AGO,
            result_code,
            native_session_id,
        ),
    )


def _complete_tool(conn, session_id: str, tool_name: str) -> None:
    conn.execute(
        "INSERT INTO events "
        "(event_id, source_type, session_id, event_kind, event_type, event_name, "
        "tool_name, created_at) VALUES (%s, 'hook', %s, 'system', 'tool_call', "
        "'HarnessToolCallCompleted', %s, %s)",
        (f"event-{session_id}-{tool_name}", session_id, tool_name, LONG_AGO),
    )


@pytest.fixture
def fleet(test_db):
    """Two ordinary workers and one item, before any failure is introduced."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    insert_item(
        test_db,
        id=1,
        title="Some work",
        status="implementing",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
    )
    test_db.commit()
    return test_db


@pytest.mark.parametrize(
    ("turn_posture", "tool_name", "past_idle_threshold", "expected"),
    [
        ("waiting", "Monitor", True, True),
        ("running", "Monitor", True, False),
        ("waiting", "Bash", True, False),
        ("waiting", "Monitor", False, False),
    ],
)
def test_only_the_full_monitor_freeze_signature_is_suspected(
    fleet, turn_posture, tool_name, past_idle_threshold, expected
):
    fleet.execute(
        "UPDATE harness_sessions SET turn_posture = %s WHERE session_id = %s",
        (turn_posture, ASKER),
    )
    _complete_tool(fleet, ASKER, tool_name)
    fleet.commit()

    idle = [quiet_holder(ASKER)] if past_idle_threshold else []
    matches = suspected_orphaned_waiters(fleet, idle=idle)

    assert bool(matches) is expected
    if matches:
        assert matches[0].session_id == ASKER
        assert matches[0].public_ref == "YOK-1"


def test_a_launch_past_its_deadline_with_no_session_is_reported(fleet):
    _launch(fleet, "launch-1", deadline=LONG_AGO)
    fleet.commit()

    overdue = unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.launch_id for entry in overdue] == ["launch-1"]
    assert overdue[0].surface == "codex-cli"
    assert overdue[0].overdue_seconds == 3 * 3600


def test_identity_parse_failure_is_reported_before_the_deadline(fleet):
    _launch(
        fleet,
        "launch-parse-failed",
        deadline="2026-08-26T12:10:00Z",
        state="outcome_unknown",
        result_code="identity_parse_failed",
    )
    fleet.commit()

    gaps = unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.launch_id for entry in gaps] == ["launch-parse-failed"]
    assert gaps[0].overdue_seconds == 0
    assert gaps[0].result_code == "identity_parse_failed"


def test_provider_model_rejection_is_reported_with_bounded_detail(fleet):
    _launch(
        fleet,
        "launch-model-rejected",
        deadline="2026-08-26T12:10:00Z",
        state="failed",
        result_code="model_combo_unsupported",
    )
    fleet.execute(
        "UPDATE session_launches SET result_evidence = %s WHERE launch_id = %s",
        (
            json.dumps({"probe_detail": "model does not support effort max"}),
            "launch-model-rejected",
        ),
    )
    fleet.commit()

    gaps = unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.launch_id for entry in gaps] == ["launch-model-rejected"]
    assert gaps[0].detail == "model does not support effort max"


def test_exact_registered_session_with_missing_launch_binding_is_named(fleet):
    _launch(
        fleet,
        "launch-existing-session",
        deadline="2026-08-26T12:10:00Z",
        state="outcome_unknown",
        result_code="late_native_requires_reconciliation",
        native_session_id=ANSWERER,
    )
    fleet.commit()

    gaps = unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.launch_id for entry in gaps] == ["launch-existing-session"]
    assert gaps[0].observed_session_id == ANSWERER
    assert gaps[0].overdue_seconds == 0


def test_a_launch_that_registered_a_session_is_not_reported(fleet):
    _launch(fleet, "launch-1", deadline=LONG_AGO)
    fleet.execute(
        "UPDATE session_launches SET registered_session_id = %s WHERE launch_id = %s",
        (ANSWERER, "launch-1"),
    )
    fleet.commit()

    assert unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_launch_the_deadline_sweep_already_closed_is_not_reported(fleet):
    """A closed launch needs no reconcile; including them grows without bound."""
    _launch(fleet, "launch-1", deadline=LONG_AGO, state="expired")
    fleet.commit()

    assert unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_merged_branch_on_an_open_item_is_reported(fleet):
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    fleet.commit()

    landed = landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.item_id for entry in landed] == [1]
    assert landed[0].status == "implementing"
    assert landed[0].landed_seconds == 3 * 3600


def test_a_merged_branch_on_a_closed_item_is_not_reported(fleet):
    fleet.execute(
        "UPDATE items SET merged_at = %s, status = 'done' WHERE id = 1",
        (LONG_AGO,),
    )
    fleet.commit()

    assert landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_queue_landing_counts_as_the_branch_landing(fleet):
    fleet.execute(
        "UPDATE items SET merge_queue_landed_at = %s WHERE id = 1",
        (LONG_AGO,),
    )
    fleet.commit()

    landed = landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.item_id for entry in landed] == [1]
    # Nothing holds the item, and that is the answer the report needs: this
    # landing needs a seat rather than a message.
    assert landed[0].holder_session_id == ""


def _claim_item(conn, session_id: str, *, item_id: int = 1, **columns) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat, released_at) "
        "VALUES (%s, 'item', %s, %s, %s, %s)",
        (
            session_id,
            json.dumps({"item_id": item_id}),
            LONG_AGO,
            LONG_AGO,
            columns.get("released_at"),
        ),
    )


def test_a_landing_its_claim_holder_still_holds_names_that_session(fleet):
    """Close-out holds the claim, so the holder IS the recovery path."""
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    _claim_item(fleet, ASKER)
    fleet.commit()

    landed = landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW)

    assert landed[0].holder_session_id == ASKER


def test_a_landing_whose_holder_ended_reports_no_live_holder(fleet):
    """An ended session cannot be asked to close out.

    Naming it would point the seat at a recovery that cannot happen, which
    is the state this row exists to make actionable.
    """
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (LONG_AGO, ASKER),
    )
    _claim_item(fleet, ASKER)
    fleet.commit()

    landed = landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW)

    assert landed[0].holder_session_id == ""


def test_a_released_claim_is_not_a_live_holder(fleet):
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    _claim_item(fleet, ASKER, released_at=NOW)
    fleet.commit()

    landed = landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW)

    assert landed[0].holder_session_id == ""
