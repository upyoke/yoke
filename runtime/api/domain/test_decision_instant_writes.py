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
from yoke_core.domain.decision_request_subject_state import (
    require_decision_request_subject_ended,
)
from yoke_core.domain.decision_requests import create_decision_request
from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
from yoke_core.domain.qa_review_requests import apply_qa_review_resolution


def _machine_request(conn, *, subject, clock, expires):
    return create_decision_request(
        conn,
        kind="machine_approval",
        subject_type="machine_auth_request",
        subject_key=subject,
        org_id=9100,
        named_actor_ids=[9101],
        subject_context={"expires_at": expires, "label": "2026-01-01"},
        created_at=clock,
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
    first, created = _machine_request(
        test_db,
        subject="approval",
        clock=equivalent,
        expires=format_instant(later),
    )
    assert created and first["created_at"] == anchor
    assert first["resolved_at"] is None
    again, created = _machine_request(
        test_db,
        subject="approval",
        clock=anchor,
        expires=format_instant(later),
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
    second, _ = _machine_request(
        test_db,
        subject="expired",
        clock=anchor,
        expires=equivalent,
    )
    with pytest.raises(ValueError, match="has not ended"):
        withdraw_for_ended_subject(
            test_db,
            second["id"],
            reason="Expired",
            withdrawn_at=anchor - timedelta(microseconds=1),
        )
    withdrawn = withdraw_for_ended_subject(
        test_db,
        second["id"],
        reason="Expired",
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
            kind="machine_approval",
            subject_type="machine_auth_request",
            subject_key="invalid-context",
            org_id=9100,
            named_actor_ids=[9101],
            created_at="2026-01-01T00:00:00Z",
            subject_context={"expires_at": bad},
        ),
        lambda: create_decision_request(
            conn,
            kind="machine_approval",
            subject_type="machine_auth_request",
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
        lambda: require_decision_request_subject_ended(
            conn,
            {
                "id": 1,
                "kind": "machine_approval",
                "subject_context": {"expires_at": bad},
            },
            observed_at="2026-01-02T00:00:00.000000Z",
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
        request, _ = create_decision_request(
            conn,
            kind="machine_approval",
            subject_type="machine_auth_request",
            subject_key="sqlite-clock",
            org_id=1,
            named_actor_ids=[5],
            created_at=stamp,
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


@pytest.mark.parametrize("field", ["occurred_at", "expires_at"])
@pytest.mark.parametrize(
    "bad", ["", "2026-01-01", "2026-01-01T00:00:00", 0, 1767225600]
)
def test_machine_delivery_validates_original_clock_values_before_coercion(field, bad):
    from pydantic import ValidationError
    from yoke_core.domain.handlers.inbox_decision_models import (
        MachineApprovalLifecycleRequest,
    )

    values = {
        "authorization_id": "5b234860-c927-46ab-b19a-9fb36df056aa",
        "state": "pending",
        "occurred_at": "2026-01-01T00:00:00.000001Z",
        "expires_at": "2026-01-01T00:10:00.000001Z",
    }
    values[field] = bad
    with pytest.raises(ValidationError):
        MachineApprovalLifecycleRequest.model_validate(values)


def test_machine_context_formats_only_declared_clocks_and_preserves_nulls():
    from yoke_core.domain.decision_machine_clocks import machine_context_wire

    assert machine_context_wire(
        {
            "expires_at": "1969-12-31T18:59:59.999999-05:00",
            "ended_at": None,
            "label": "2026-01-01",
            "note": "opaque",
        }
    ) == {
        "expires_at": "1969-12-31T23:59:59.999999Z",
        "ended_at": None,
        "label": "2026-01-01",
        "note": "opaque",
    }
    for key in ["expires_at", "ended_at", "expired_at", "occurred_at", "withdrawn_at"]:
        with pytest.raises(InvalidInstant):
            machine_context_wire({key: "2026-01-01"})
