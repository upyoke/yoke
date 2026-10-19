"""Decision lifecycles preserve native instants and canonical audit views."""

import json
from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import (
    InvalidInstant,
    format_instant,
    parse_instant,
    temporal_wire,
)
from yoke_core.domain.approval_decisions import record_decision
from yoke_core.domain.decision_request_events import append_decision_event
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
    withdraw_decision_request,
    withdraw_for_ended_subject,
)
from yoke_core.domain.decision_requests import create_decision_request
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
from yoke_core.domain.qa_review_requests import apply_qa_review_resolution


def _transition_request(conn, *, item_id, clock, project_id, actor_id):
    return create_decision_request(
        conn,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key=f"{item_id}:reviewing-implementation",
        project_id=project_id,
        named_actor_ids=[actor_id],
        created_at=clock,
        subject_context={
            "item_id": item_id,
            "item_ref": f"YOK-{item_id}",
            "item_title": "Clock check",
            "from_stage": "implementing",
            "to_stage": "reviewing-implementation",
            "workflow_id": "issue",
            "workflow_version_id": 1,
            "branch_changes": {
                "branch": None,
                "commit_sha": None,
                "touched_files": [],
                "summary": "No implementation branch is recorded.",
            },
            "approval_source": {
                "kind": "workflow_approval_default",
                "entry": "approval_defaults.reviewing-implementation",
            },
            "label": "2026-01-01",
        },
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_decisions_and_withdrawals_bind_native_clocks_and_atomic_audits(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    anchor = parse_instant("1969-12-31T23:59:59.999999Z")
    equivalent = "1969-12-31T18:59:59.999999-05:00"
    later = anchor + timedelta(microseconds=1)
    test_db.execute(
        "INSERT INTO organizations (id,slug,name,created_at) VALUES (%s,%s,%s,%s)",
        (9100, "instant-decisions", "Native decisions", anchor),
    )
    test_db.execute(
        "INSERT INTO actors (id,kind,created_at) VALUES (%s,'human',%s)",
        (9101, anchor),
    )
    seed_project_identities(test_db)
    project_id = resolve_project_id(test_db, "yoke")
    first, created = _transition_request(
        test_db,
        item_id=9102,
        clock=equivalent,
        project_id=project_id,
        actor_id=9101,
    )
    assert created and first["created_at"] == anchor
    assert first["resolved_at"] is None
    again, created = _transition_request(
        test_db,
        item_id=9102,
        clock=anchor,
        project_id=project_id,
        actor_id=9101,
    )
    assert not created and again["id"] == first["id"]
    resolved = resolve_decision_request(
        test_db,
        first["id"],
        actor_id=9101,
        action="approve",
        resolved_at=later,
    )
    assert resolved["resolved_at"] == later
    assert resolved["decisions"][0]["decided_at"] == format_instant(later)
    assert temporal_wire(resolved)["created_at"] == format_instant(anchor)
    # A removed subject makes withdrawal valid; the timestamp storage contract
    # is the same for any active decision kind.
    second, _ = _transition_request(
        test_db,
        item_id=9103,
        clock=anchor,
        project_id=project_id,
        actor_id=9101,
    )
    withdrawn = withdraw_for_ended_subject(
        test_db,
        second["id"],
        reason="Subject removed",
        withdrawn_at=equivalent,
    )
    assert withdrawn["withdrawn_at"] == anchor
    assert withdrawn["subject_context"]["label"] == "2026-01-01"
    decision = test_db.execute(
        "SELECT decided_at FROM decision_request_decisions WHERE request_id=%s",
        (first["id"],),
    ).fetchone()[0]
    assert isinstance(decision, datetime) and decision == later
    events = test_db.execute(
        "SELECT event_name,created_at,envelope FROM events "
        "WHERE event_type='decision_request' ORDER BY id"
    ).fetchall()
    assert [row[0] for row in events] == [
        "DecisionRequestCreated",
        "DecisionRecorded",
        "DecisionRequestResolved",
        "DecisionRequestCreated",
        "DecisionRequestWithdrawn",
    ]
    for event in events:
        envelope = event[2] if isinstance(event[2], dict) else json.loads(event[2])
        assert isinstance(event[1], datetime) and event[1].tzinfo is not None
        assert envelope["created_at"] == format_instant(event[1])


@pytest.mark.parametrize(
    "bad", ["", "2026-01-01", "2026-01-01T00:00:00", datetime(2026, 1, 1)]
)
def test_bad_owned_clocks_refuse_before_sql(bad):
    class NoSQL:
        def rollback(self):
            pass

        def execute(self, *_args, **_kwargs):
            raise AssertionError("clock admission must precede SQL")

    conn = NoSQL()
    calls = [
        lambda: create_decision_request(
            conn,
            kind="lifecycle_transition_approval",
            subject_type="item_transition",
            subject_key="invalid",
            org_id=9100,
            named_actor_ids=[9101],
            created_at=bad,
        ),
        lambda: resolve_decision_request(
            conn, 1, actor_id=1, action="approve", resolved_at=bad
        ),
        lambda: withdraw_decision_request(
            conn, 1, reason="Ended", actor_id=1, withdrawn_at=bad
        ),
        lambda: withdraw_for_ended_subject(conn, 1, reason="Ended", withdrawn_at=bad),
        lambda: record_decision(
            conn, request_id=1, actor_id=1, action="approve", note=None, decided_at=bad
        ),
        lambda: append_decision_event(
            conn,
            "DecisionRequestCreated",
            actor_id=1,
            session_id="",
            project_id=None,
            org_id=9100,
            context={},
            created_at=bad,
        ),
        lambda: apply_qa_review_resolution(
            conn,
            requirement_id=1,
            action="waive",
            actor_id=1,
            note=None,
            resolved_at=bad,
        ),
        lambda: terminalize_run_on(
            conn,
            "invalid",
            disposition="cancelled",
            reason="Ended",
            actor_id=1,
            session_id="",
            terminalized_at=bad,
        ),
    ]
    for call in calls:
        with pytest.raises(InvalidInstant):
            call()


def test_sqlite_decisions_and_audit_clocks_have_canonical_text():
    from runtime.api.domain.decision_request_test_support import (
        decision_request_connection,
    )

    with decision_request_connection() as conn:
        stamp = parse_instant("1969-12-31T23:59:59.999999Z")
        request, _ = _transition_request(
            conn,
            item_id=9102,
            clock=stamp,
            project_id=10,
            actor_id=5,
        )
        assert request["created_at"] == format_instant(stamp)
        result = resolve_decision_request(
            conn,
            request["id"],
            actor_id=5,
            action="approve",
            resolved_at="1970-01-01T01:00:00.000000+01:00",
        )
        assert result["resolved_at"] == "1970-01-01T00:00:00.000000Z"
        for row in conn.execute("SELECT created_at,envelope FROM events"):
            assert row[0] == format_instant(row[0])
            assert json.loads(row[1])["created_at"] == row[0]
