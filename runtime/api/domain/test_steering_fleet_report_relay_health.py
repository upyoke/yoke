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
    assert projected["relay_health"][0]["state"] == "quarantined"
    assert projected["relay_health"][0]["error_code"] == "payload_invalid"


def test_retry_failure_appears_only_after_it_is_sustained(fleet) -> None:
    recent = {
        "pending_reports": 1,
        "report_failure": {
            "error_code": "transport_error",
            "failure_count": 2,
            "first_failed_at": "2026-08-26T11:59:30Z",
            "last_failed_at": NOW,
        },
    }
    _publish(fleet, recent)
    assert compose(fleet).relay_health == ()

    recent["report_failure"]["first_failed_at"] = "2026-08-26T11:55:00Z"
    _publish(fleet, recent)
    assert compose(fleet).relay_health[0].error_code == "transport_error"


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
