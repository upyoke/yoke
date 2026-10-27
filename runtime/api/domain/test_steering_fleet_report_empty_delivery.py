"""Empty hook reports settle their fingerprint without a delivery."""

from datetime import datetime, timezone
from unittest.mock import Mock

from yoke_core.domain import steering_fleet_report_delivery as delivery
from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest


def test_empty_report_stamps_fingerprint_without_delivery(monkeypatch):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    combined = CombinedFleetReport(composed_at=now, sections=(), unattended=())
    assert combined_hook_digest(combined) == ""
    monkeypatch.setattr(delivery, "claim_report_composition", lambda *a, **k: now)
    monkeypatch.setattr(delivery, "_last_report", lambda *a: (None, ""))
    compose = Mock(return_value=combined)
    monkeypatch.setattr(delivery, "compose_held_reports", compose)
    confirm = Mock(return_value=True)
    monkeypatch.setattr(delivery, "confirm_steering_report_delivery", confirm)
    assert (
        delivery.steering_report_candidate(None, session_id="holder", now=now) is None
    )
    assert confirm.call_args.args[1].fingerprint == combined.fingerprint()
    monkeypatch.setattr(
        delivery, "_last_report", lambda *a: (now, combined.fingerprint())
    )
    assert (
        delivery.steering_report_candidate(None, session_id="holder", now=now) is None
    )
    assert confirm.call_count == 1
