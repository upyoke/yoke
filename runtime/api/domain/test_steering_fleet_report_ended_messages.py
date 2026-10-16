"""Ended-session debt reaches real report composition without mutation."""

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ANSWERER,
    ASKER,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    compose,
    seed_message,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
    combined_body,
)
from yoke_core.domain.steering_fleet_report_delivery_states import RECIPIENT_ENDED
from yoke_core.domain.steering_fleet_report_render import report_body


@pytest.fixture
def fleet(test_db):
    seed_steering_scope(test_db)
    seed_session(test_db, ASKER)
    seed_session(test_db, ANSWERER, ended_at=JUST_NOW)
    test_db.execute(
        "UPDATE harness_sessions SET recent_item_id=%s WHERE session_id=%s",
        ("1", ANSWERER),
    )
    test_db.commit()
    return test_db


@pytest.mark.parametrize(
    "state,injections", [("pending", 0), ("injected", 1), ("pending", 1)]
)
def test_ended_debt_has_context_and_does_not_mutate(fleet, state, injections):
    seed_message(
        fleet, "ended-mail", sender=ASKER, to=ANSWERER, at=LONG_AGO, state=state
    )
    fleet.execute(
        "UPDATE session_message_recipients SET injection_count=%s", (injections,)
    )
    fleet.commit()
    report = compose(fleet)
    (row,) = report.undelivered
    assert row.delivery_state == RECIPIENT_ENDED
    assert row.item_id == 1 and row.public_ref and row.item_project
    assert row.envelope_count == 1 and row.oldest_seconds > 0
    body = report_body(report)
    assert "ended-mail" in body and ANSWERER in body and row.public_ref in body
    assert "yoke messages get ended-mail" in body
    assert "yoke messages cancel ended-mail" in body
    receipt = fleet.execute(
        "SELECT state, injection_count, acknowledged_at FROM session_message_recipients "
        "WHERE message_id=%s",
        ("ended-mail",),
    ).fetchone()
    assert tuple(receipt) == (state, injections, None)


@pytest.mark.parametrize("state", ["acknowledged", "cancelled", "expired"])
def test_settled_receipts_are_excluded(fleet, state):
    seed_message(fleet, "settled", sender=ASKER, to=ANSWERER, at=LONG_AGO, state=state)
    fleet.commit()
    assert compose(fleet).undelivered == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"ended_at": None},
        {"mode": "parked"},
        {"turn_posture": "waiting"},
    ],
)
def test_active_or_resumable_injected_receipts_stay_out(fleet, changes):
    seed_message(
        fleet, "paused-mail", sender=ASKER, to=ANSWERER, at=LONG_AGO, state="injected"
    )
    for key, value in changes.items():
        fleet.execute(
            f"UPDATE harness_sessions SET {key}=%s WHERE session_id=%s",
            (value, ANSWERER),
        )
    fleet.commit()
    assert compose(fleet).undelivered == ()


def test_document_scope_without_live_claim_and_combined_deduplication(fleet):
    seed_message(
        fleet, "linked-mail", sender=ASKER, to=ANSWERER, at=LONG_AGO, state="injected"
    )
    fleet.execute(
        "INSERT INTO item_strategy_docs (item_id,project_id,strategy_doc_slug,linked_at) "
        "VALUES (%s,%s,%s,%s)",
        (1, PROJECT_ID, "CURRENT-PLAN", NOW),
    )
    fleet.commit()
    linked = compose(
        fleet, scope={"project_id": PROJECT_ID, "document": "CURRENT-PLAN"}
    )
    other = compose(fleet, scope={"project_id": PROJECT_ID, "document": "VISION"})
    assert linked.undelivered[0].message_ids == ("linked-mail",)
    assert other.undelivered == ()
    combined = CombinedFleetReport(
        linked.composed_at,
        (
            ScopedFleetReport("project", compose(fleet)),
            ScopedFleetReport("document", linked),
        ),
    )
    assert combined_body(combined).count("[linked-mail]") == 1
    from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest

    assert combined_hook_digest(combined).count("[linked-mail]") == 1


def test_new_debt_on_same_recipient_changes_identity(fleet):
    seed_message(fleet, "first-mail", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.commit()
    before = compose(fleet)
    seed_message(
        fleet, "second-mail", sender=ASKER, to=ANSWERER, at=LONG_AGO, state="injected"
    )
    fleet.commit()
    after = compose(fleet)
    assert before.fingerprint() != after.fingerprint()
    assert len(after.undelivered) == 1 and after.undelivered[0].envelope_count == 2


def test_envelope_settlement_before_sweep(fleet):
    seed_message(
        fleet,
        "cancelled-mail",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        state="injected",
        cancelled_at=JUST_NOW,
    )
    seed_message(
        fleet,
        "expired-mail",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        state="injected",
        expires_at=JUST_NOW,
    )
    fleet.commit()
    assert compose(fleet).undelivered == ()


def test_protected_message_uses_existing_visibility(fleet, monkeypatch):
    seed_message(
        fleet,
        "protected-mail",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        state="injected",
    )
    from yoke_core.domain import steering_fleet_report_undelivered as receipts

    monkeypatch.setattr(receipts, "visible_clause", lambda *args, **kwargs: ("1=0", []))
    assert compose(fleet).undelivered == ()


def test_project_and_message_access_boundaries(fleet):
    from yoke_core.domain.actor_permissions import ROLE_VIEWER, grant_actor_project_role
    from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages

    fleet.execute(
        "INSERT INTO actors (id,name,kind,created_at) VALUES (%s,%s,'human',%s)",
        (99, "Scoped reader", NOW),
    )
    grant_actor_project_role(
        fleet, actor_id=99, project_id=PROJECT_ID, role_name=ROLE_VIEWER
    )
    fleet.execute(
        "INSERT INTO projects (id,org_id,slug,name,public_item_prefix,created_at) "
        "SELECT 99,org_id,'private-project','Private project','PRV',created_at FROM projects WHERE id=%s",
        (PROJECT_ID,),
    )
    seed_session(fleet, "scoped-reader")
    seed_session(fleet, "private-recipient", ended_at=JUST_NOW)
    fleet.execute(
        "UPDATE harness_sessions SET actor_id=99 WHERE session_id=%s",
        ("scoped-reader",),
    )
    seed_message(
        fleet, "visible-mail", sender=ASKER, to=ANSWERER, at=LONG_AGO, state="injected"
    )
    seed_message(
        fleet,
        "protected-mail",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        state="injected",
    )
    fleet.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,state,created_at,wake_after,injection_count) "
        "SELECT message_id,'private-recipient',99,resolution_evidence,routing_snapshot,state,created_at,wake_after,1 "
        "FROM session_message_recipients WHERE message_id='protected-mail'",
    )
    seed_message(
        fleet,
        "private-mail",
        sender=ASKER,
        to="private-recipient",
        at=LONG_AGO,
        state="injected",
    )
    fleet.execute(
        "UPDATE session_message_recipients SET project_id=99 WHERE message_id='private-mail'"
    )
    fleet.commit()
    rows = undelivered_messages(
        fleet, project_id=PROJECT_ID, now=NOW, session_id="scoped-reader"
    )
    assert [row.message_ids for row in rows] == [("visible-mail",)]


@pytest.mark.parametrize(
    "surface", ["codex-cli", "claude-cli", "cursor-cli", "codex-desktop"]
)
def test_terminated_injected_debt_does_not_depend_on_harness(fleet, surface):
    fleet.execute(
        "UPDATE harness_sessions SET executor_surface=%s,terminated_at=%s,mode=%s WHERE session_id=%s",
        (surface, JUST_NOW, "parked", ANSWERER),
    )
    seed_message(
        fleet,
        "terminated-mail",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        state="injected",
    )
    fleet.commit()
    assert compose(fleet).undelivered[0].delivery_state == "recipient_terminated"
