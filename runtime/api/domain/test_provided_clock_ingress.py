"""Supplied clocks refuse before action and retain qualified microseconds."""

from datetime import datetime
from importlib import import_module

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
BAD_CLOCKS = ("", 123, "2026-10-09", datetime(2026, 10, 9), "2026-10-09T15:00:00-00:00")

# Actual public owners; required business arguments are valid independently
# of the refused clock, so no incidental argument error can hide a write.
OWNERS = (
    (
        "deployment_delivery_close_out_notice",
        "notify_delivery_cleared",
        {"run_id": "run"},
    ),
    ("deployment_delivery_done_notice", "notify_delivery_done", {"item_id": 1}),
    (
        "deployment_qa_member_acceptance_notice",
        "notify_item_qa_accepted",
        {"run_id": "run", "item_id": 1},
    ),
    (
        "deployment_qa_result_notice",
        "notify_qa_stage_result",
        {
            "notification": None,
            "run_id": "run",
            "stage_name": "qa",
            "member_item_id": 1,
            "project_id": 1,
            "outcome": "passed",
            "subject": "sample",
        },
    ),
    (
        "deployment_qa_stage_wake",
        "notify_item_scoped_qa_wait",
        {
            "run_id": "run",
            "stage_name": "qa",
            "item_id": 1,
            "project_id": 1,
            "reasons": "waiting",
            "names_cases": False,
        },
    ),
    (
        "deployment_qa_verdict_notice",
        "notify_deployment_qa_verdict",
        {"requirement_id": 1, "action": "accept"},
    ),
    (
        "deployment_run_driver_notice",
        "push_run_scoped_notice",
        {
            "project_id": 1,
            "body_for_route": lambda route: "sample",
            "idempotency_key": "key",
        },
    ),
    (
        "deployment_run_driver_notice",
        "push_member_notice",
        {
            "item_id": 1,
            "project_id": 1,
            "body_for_route": lambda route: "sample",
            "idempotency_key": "key",
        },
    ),
    ("session_operator_wake_notice", "settle_operator_wake_notices", {"actor_id": 1}),
    (
        "session_process_liveness_report",
        "apply_verified_process_death_reports",
        {"machine_id": "machine", "authorized_projects": (1,), "reports": ()},
    ),
    ("sessions_steering_visibility", "steering_visibility", {"rows": []}),
)


class UntouchedConnection:
    def execute(self, *args, **kwargs):
        raise AssertionError("invalid clock reached SQL")


def unused_clock():
    raise AssertionError("a supplied clock evaluated the default")


@pytest.mark.parametrize("clock", BAD_CLOCKS)
@pytest.mark.parametrize("module_name,function_name,arguments", OWNERS)
def test_invalid_notice_and_session_clock_refuses_before_action(
    monkeypatch,
    module_name,
    function_name,
    arguments,
    clock,
):
    owner = import_module(f"yoke_core.domain.{module_name}")
    monkeypatch.setattr(owner, "utc_now", unused_clock)
    with pytest.raises(InvalidInstant):
        getattr(owner, function_name)(UntouchedConnection(), now=clock, **arguments)


@pytest.mark.parametrize("clock", BAD_CLOCKS)
def test_invalid_clock_refuses_before_connect_sign_or_export_name(monkeypatch, clock):
    from yoke_core.domain import item_execution_status, s3_presign, universe_export

    for owner in (item_execution_status, s3_presign, universe_export):
        monkeypatch.setattr(owner, "utc_now", unused_clock)
    monkeypatch.setattr(item_execution_status, "connect", unused_clock)
    with pytest.raises(InvalidInstant):
        item_execution_status.build_projection(1, now=clock)
    with pytest.raises(InvalidInstant):
        s3_presign.presign_for_host(
            method="GET",
            host="sample",
            canonical_uri="/",
            region="region",
            credentials=object(),
            now=clock,
        )
    with pytest.raises(InvalidInstant):
        universe_export.default_artifact_name("sample", now=clock)


@pytest.mark.parametrize("member", (False, True))
@pytest.mark.parametrize("clock", (INSTANT, "2026-10-09T20:45:00.123456+05:45", None))
def test_driver_notices_forward_one_native_microsecond_clock(
    monkeypatch, member, clock
):
    from yoke_core.domain import deployment_run_driver_notice as owner
    from yoke_core.domain import merge_queue_landing_notice

    monkeypatch.setattr(
        owner, "utc_now", (lambda: INSTANT) if clock is None else unused_clock
    )
    monkeypatch.setattr(
        owner,
        "resolve_run_driver_recipient",
        lambda *args, **kwargs: ("session", 1, "driver"),
    )
    monkeypatch.setattr(
        merge_queue_landing_notice,
        "resolve_lane_recipient",
        lambda *args, **kwargs: ("session", 1, "holder"),
    )
    delivered = []

    def deliver(conn, **kwargs):
        delivered.append(kwargs)
        return "delivered"

    monkeypatch.setattr(owner, "_deliver", deliver)
    arguments = dict(
        project_id=1,
        body_for_route=lambda route: f"sample {route}",
        idempotency_key="key",
        now=clock,
    )
    if member:
        result = owner.push_member_notice(UntouchedConnection(), item_id=1, **arguments)
    else:
        result = owner.push_run_scoped_notice(UntouchedConnection(), **arguments)
    assert result == "delivered"
    assert len(delivered) == 1
    assert delivered[0]["now"] == INSTANT
    assert delivered[0]["now"].microsecond == 123456
    assert delivered[0]["body"] == ("sample holder" if member else "sample driver")


def test_invalid_generated_clock_refuses_before_recipient_lookup(monkeypatch):
    from yoke_core.domain import deployment_run_driver_notice as owner

    monkeypatch.setattr(owner, "utc_now", lambda: datetime(2026, 10, 9))
    monkeypatch.setattr(owner, "resolve_run_driver_recipient", unused_clock)
    with pytest.raises(InvalidInstant):
        owner.push_run_scoped_notice(
            UntouchedConnection(),
            project_id=1,
            body_for_route=lambda route: "sample",
            idempotency_key="key",
        )


@pytest.mark.parametrize("clock", (*BAD_CLOCKS, INSTANT, None))
def test_hook_clock_reaches_existing_captured_endpoint_owner(monkeypatch, clock):
    from yoke_core.domain import observe_cli

    monkeypatch.setattr(
        observe_cli, "utc_now", (lambda: INSTANT) if clock is None else unused_clock
    )
    captured = []

    def parse(data, **kwargs):
        captured.append(kwargs["completed_at"])
        return None

    monkeypatch.setattr(observe_cli, "parse_hook_event", parse)
    observe_cli.record_hook_event({}, completed_at=clock)
    assert captured == [INSTANT if clock is None else clock]
