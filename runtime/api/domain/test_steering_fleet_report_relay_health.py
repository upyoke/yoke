"""Fleet reporting for sustained and quarantined relay delivery failures."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    NOW,
    compose,
    seed_steering_scope,
)
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body


@pytest.fixture
def fleet(test_db):
    return seed_steering_scope(test_db)


def _publish(fleet, health: dict) -> None:
    fleet.execute(
        "UPDATE session_relays SET relay_health=%s WHERE relay_id='relay-1'",
        (json.dumps(health),),
    )
    fleet.commit()


def test_quarantine_is_actionable_in_text_and_projection(fleet) -> None:
    _publish(
        fleet,
        {
            "quarantined_reports": [
                {
                    "report_id": "report-hash",
                    "job_kind": "launch",
                    "error_code": "payload_invalid",
                    "attempts": 3,
                    "quarantined_at": NOW,
                }
            ]
        },
    )

    report = compose(fleet)
    rendered = report_body(report)
    projected = report_dict(report)

    assert report.actionable is True
    assert "rejected report(s) quarantined" in rendered
    assert "run `yoke relay status`" in rendered
    assert "restore wire/transport compatibility" in rendered
    assert "do not replay server-settled reports" in rendered
    assert projected["relay_health"][0]["state"] == "quarantined"
    assert projected["relay_health"][0]["error_code"] == "payload_invalid"


def test_retry_failure_appears_only_after_it_is_sustained(fleet) -> None:
    recent = {
        "pending_reports": 1,
        "report_failure": {
            "error_code": "transport_error",
            "failure_count": 2,
            "first_failed_at": "2026-08-26T11:59:30.000000Z",
            "last_failed_at": NOW,
        },
    }
    _publish(fleet, recent)
    assert compose(fleet).relay_health == ()

    recent["report_failure"]["first_failed_at"] = "2026-08-26T11:55:00.000000Z"
    _publish(fleet, recent)
    report = compose(fleet)
    rendered = report_body(report)
    assert report.relay_health[0].error_code == "transport_error"
    assert "restore control-plane transport" in rendered
    assert "restore wire/transport compatibility" not in rendered


def test_settled_conflict_quarantine_is_not_fleet_actionable(fleet) -> None:
    _publish(
        fleet,
        {
            "quarantined_reports": [
                {
                    "report_id": "settled-hash",
                    "job_kind": "launch",
                    "error_code": "report_conflict",
                    "attempts": 2144,
                    "quarantined_at": NOW,
                }
            ]
        },
    )

    report = compose(fleet)
    rendered = report_body(report)

    assert report.relay_health == ()
    assert "attention required" not in rendered
    assert "restore wire/transport compatibility" not in rendered


def test_all_server_settled_quarantines_are_not_fleet_actionable(fleet) -> None:
    codes = [
        "report_conflict",
        "report_conflict",
        "attempt_missing",
        "relay_lease_expired",
        "invalid_state",
        "lease_mismatch",
    ]
    _publish(
        fleet,
        {
            "quarantined_reports": [
                {
                    "report_id": f"settled-{index}",
                    "job_kind": "launch",
                    "error_code": code,
                    "attempts": 3,
                    "quarantined_at": NOW,
                }
                for index, code in enumerate(codes)
            ]
        },
    )

    report = compose(fleet)

    assert report.relay_health == ()
    assert "attention required" not in report_body(report)


@pytest.mark.parametrize(
    "contract_code",
    ["payload_invalid", "relay_report_payload_invalid", "request_validation_failed"],
)
def test_contract_rejection_among_settled_quarantines_stays_actionable(
    fleet, contract_code: str
) -> None:
    _publish(
        fleet,
        {
            "quarantined_reports": [
                {
                    "report_id": "settled-lease",
                    "job_kind": "launch",
                    "error_code": "relay_lease_expired",
                    "attempts": 3,
                    "quarantined_at": NOW,
                },
                {
                    "report_id": "contract",
                    "job_kind": "wake",
                    "error_code": contract_code,
                    "attempts": 3,
                    "quarantined_at": NOW,
                },
                {
                    "report_id": "settled-missing",
                    "job_kind": "launch",
                    "error_code": "attempt_missing",
                    "attempts": 3,
                    "quarantined_at": NOW,
                },
            ]
        },
    )

    report = compose(fleet)

    assert "attention required" in report_body(report)
    assert report_dict(report)["relay_health"][0]["error_code"] == contract_code


def test_mixed_quarantines_stay_actionable_and_name_unsettled_code(fleet) -> None:
    _publish(
        fleet,
        {
            "quarantined_reports": [
                {
                    "report_id": "older-contract",
                    "job_kind": "launch",
                    "error_code": "payload_invalid",
                    "attempts": 3,
                    "quarantined_at": "2026-08-26T11:00:00.000000Z",
                },
                {
                    "report_id": "later-conflict",
                    "job_kind": "launch",
                    "error_code": "report_conflict",
                    "attempts": 3,
                    "quarantined_at": NOW,
                },
            ]
        },
    )

    report = compose(fleet)
    rendered = report_body(report)
    projected = report_dict(report)["relay_health"][0]

    assert report.relay_health
    assert "attention required" in rendered
    assert "restore wire/transport compatibility" in rendered
    assert "do not replay server-settled reports" in rendered
    assert projected["error_code"] == "payload_invalid"


def test_incomplete_quarantine_metadata_stays_actionable(fleet) -> None:
    _publish(
        fleet,
        {
            "quarantine_count": 2,
            "quarantined_reports": [
                {
                    "report_id": "visible-conflict",
                    "job_kind": "launch",
                    "error_code": "report_conflict",
                    "attempts": 3,
                    "quarantined_at": NOW,
                }
            ],
        },
    )

    report = compose(fleet)
    rendered = report_body(report)

    assert report.relay_health
    assert "attention required" in rendered
    assert report_dict(report)["relay_health"][0]["error_code"] == "report_conflict"


def test_non_contract_quarantine_does_not_name_a_wire_mismatch(fleet) -> None:
    _publish(
        fleet,
        {
            "quarantined_reports": [
                {
                    "report_id": "invalid-pending",
                    "job_kind": "unknown",
                    "error_code": "pending_report_invalid",
                    "attempts": 1,
                    "quarantined_at": NOW,
                }
            ]
        },
    )

    rendered = report_body(compose(fleet))

    assert "attention required" in rendered
    assert "restore wire/transport compatibility" not in rendered
    assert "do not replay server-settled reports" in rendered


def test_build_refusal_names_both_revisions_and_deploy_recovery(fleet) -> None:
    _publish(
        fleet,
        {
            "run_refusal": {
                "reason": "relay_newer_than_server",
                "local_revision": "aaaaaaaaaaaa",
                "server_revision": "v0.1.1+launch.365",
                "ahead_by": 30,
                "recovery": "deploy",
            }
        },
    )

    report = compose(fleet)
    rendered = report_body(report)
    projected = report_dict(report)["relay_health"][0]

    assert report.actionable is True
    assert "relay_newer_than_server" in rendered
    assert "aaaaaaaaaaaa" in rendered
    assert "v0.1.1+launch.365" in rendered
    assert "recovery: deploy" in rendered
    assert projected["state"] == "refused"
    assert projected["refusal_reason"] == "relay_newer_than_server"
    assert "restore wire/transport compatibility" not in rendered
