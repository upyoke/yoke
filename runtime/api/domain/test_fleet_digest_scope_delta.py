"""Shared digest changes retain only the changed scope's rows."""

import json
from dataclasses import replace

from runtime.api.domain.test_steering_fleet_report_compose import NOW, _report
from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport, ScopedFleetReport
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_watcher import watcher_dict
from yoke_core.domain.steering_fleet_report import ClaimHolder


def _holder(session, item):
    return ClaimHolder(session_id=session, item_id=item, public_ref=f"work-{item}",
                       mode="busy", parked=False, last_activity_at=None, idle_seconds=2000)


def test_scope_delta_matches_hook_and_watcher():
    left = _report(1, NOW, idle=(_holder("left", 1),))
    right = _report(2, NOW, idle=(_holder("right", 2),))
    before = CombinedFleetReport(NOW, (ScopedFleetReport("alpha", left), ScopedFleetReport("beta", right)))
    changed = replace(before, sections=(before.sections[0], ScopedFleetReport("beta", replace(right, idle=(_holder("new-right", 3),)))))
    prior = before.fingerprint()
    assert isinstance(json.loads(prior), dict)
    body = combined_hook_digest(changed, prior)
    assert "new-right" in body
    assert "left" not in body
    assert "work-2" not in body
    assert watcher_dict(changed, prior)["digest"] == body
    assert combined_hook_digest(changed, changed.fingerprint()) == ""


def test_ages_do_not_change_digest_identity():
    report = _report(1, NOW, idle=(_holder("holder", 1),))
    before = CombinedFleetReport(NOW, (ScopedFleetReport("scope", report),))
    after = replace(before, sections=(ScopedFleetReport("scope", replace(report, idle=(replace(report.idle[0], idle_seconds=3000),))),))
    assert before.fingerprint() == after.fingerprint()
