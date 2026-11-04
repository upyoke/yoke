"""Retained evidence changes health only while it needs action."""

import pytest

from yoke_contracts.session_control.relay_health import (
    SETTLED_RELAY_REPORT_CODES,
    sanitize_relay_health,
)


@pytest.mark.parametrize("code", sorted(SETTLED_RELAY_REPORT_CODES))
def test_settled_reports_remain_evidence_without_degrading_health(code):
    report = {"report_id": "report", "error_code": code}
    health = sanitize_relay_health({"quarantined_reports": [report]})

    assert health["state"] == "healthy"
    assert health["quarantine_count"] == 1
    assert health["quarantined_reports"][0]["error_code"] == code
    assert sanitize_relay_health(health) == health


@pytest.mark.parametrize(
    ("extra", "state"),
    [
        ({"report_failure": {"error_code": "transport_error"}}, "retrying"),
        ({"pending_reports": 1}, "retrying"),
        ({"quarantine_count": 2}, "quarantined"),
    ],
)
def test_settled_evidence_does_not_hide_active_health(extra, state):
    health = sanitize_relay_health(
        {
            "quarantined_reports": [
                {"report_id": "settled", "error_code": "report_conflict"}
            ],
            **extra,
        }
    )

    assert health["state"] == state
    assert health["quarantined_reports"][0]["report_id"] == "settled"


@pytest.mark.parametrize("code", ["payload_invalid", ""])
def test_unsettled_or_unknown_quarantine_outranks_retrying(code):
    health = sanitize_relay_health(
        {
            "quarantined_reports": [{"report_id": "report", "error_code": code}],
            "report_failure": {"error_code": "transport_error"},
        }
    )

    assert health["state"] == "quarantined"


def test_build_refusal_outranks_actionable_quarantine():
    health = sanitize_relay_health(
        {
            "quarantined_reports": [
                {"report_id": "report", "error_code": "payload_invalid"}
            ],
            "run_refusal": {
                "reason": "relay_newer_than_server",
                "local_revision": "new",
                "server_revision": "old",
            },
        }
    )

    assert health["state"] == "refused"
