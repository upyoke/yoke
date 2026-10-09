"""Deployment approval facts remain native through SQL and public clock projection."""

from datetime import datetime

import pytest
from pydantic import ValidationError
from yoke_contracts.timestamps import InvalidInstant, parse_instant, temporal_wire
from runtime.api.deployment_stage_approval_fixture import OpenConnection
from runtime.api.domain.test_deployment_run_gates import (
    RUN_ID,
    _seed_run_awaiting_approval,
)
from yoke_core.domain import deployment_run_approval as owner
from yoke_core.domain.decision_request_schema import create_decision_request_tables
from yoke_core.domain.deployment_run_insert import insert_run
from yoke_core.domain.handlers.deployment_common import DeploymentRunApproveResponse


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_approval_clock_is_native_in_receipt_and_storage_and_wire_in_event(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    create_decision_request_tables(test_db)
    actor, _ = _seed_run_awaiting_approval(test_db)
    stamp = parse_instant("1969-12-31T23:59:59.123456Z")
    monkeypatch.setattr(owner, "connect", lambda: OpenConnection(test_db))
    monkeypatch.setattr(owner, "utc_now", lambda: stamp)
    approval = owner.approve_run(RUN_ID, actor_id=actor, session_id="clock-approver")
    assert approval.approved_at == stamp
    assert temporal_wire({"approved_at": approval.approved_at}) == {
        "approved_at": "1969-12-31T23:59:59.123456Z"
    }
    raw = test_db.execute(
        "SELECT resolved_at FROM decision_requests WHERE id=%s",
        (approval.decision_request_id,),
    ).fetchone()
    assert raw[0] == stamp
    calls = []
    from yoke_core.domain import events
    from types import SimpleNamespace

    monkeypatch.setattr(
        events,
        "emit_event",
        lambda *args, **kw: (
            calls.append(kw) or SimpleNamespace(ok=True, event_id="approval-event")
        ),
    )
    assert (
        owner.emit_run_approval(
            approval, actor_id=str(actor), session_id="clock-approver", note=None
        )
        == "approval-event"
    )
    assert calls[0]["context"]["approved_at"] == "1969-12-31T23:59:59.123456Z"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00-00:00",
        0,
        datetime(1970, 1, 1),
    ],
)
def test_run_creation_clock_refuses_before_database_access(bad):
    with pytest.raises(InvalidInstant):
        insert_run(
            object(),
            run_id="run-clock",
            project_id=1,
            flow="clock",
            target_tier=None,
            target_environment_id=None,
            release_lineage=None,
            created_by="clock-test",
            created_at=bad,
            artifact_identity=None,
        )
    with pytest.raises(ValidationError, match="invalid_instant"):
        DeploymentRunApproveResponse(
            run_id="run-clock",
            project="yoke",
            approved_stage="approve",
            next_stage="complete",
            approved_at=bad,
            member_item_ids=[],
        )


def test_public_approval_model_uses_fixed_six_utc_without_losing_native_fact():
    response = DeploymentRunApproveResponse(
        run_id="run-clock",
        project="yoke",
        approved_stage="approve",
        next_stage="complete",
        approved_at="1970-01-01T05:30:00+05:30",
        member_item_ids=[],
    )
    assert response.model_dump()["approved_at"] == parse_instant("1970-01-01T00:00:00Z")
    assert (
        response.model_dump(mode="json")["approved_at"] == "1970-01-01T00:00:00.000000Z"
    )
