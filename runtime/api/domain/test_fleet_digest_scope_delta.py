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
    # The response stays valid even when the shared delivery gate suppresses it.
    assert watcher_dict(changed, changed.fingerprint())["digest"]



def test_ages_do_not_change_digest_identity():
    report = _report(1, NOW, idle=(_holder("holder", 1),))
    before = CombinedFleetReport(NOW, (ScopedFleetReport("scope", report),))
    after = replace(before, sections=(ScopedFleetReport("scope", replace(report, idle=(replace(report.idle[0], idle_seconds=3000),))),))
    assert before.fingerprint() == after.fingerprint()


def test_removed_scopes_have_stable_order():
    current = CombinedFleetReport(NOW, ())
    prior = json.loads(current.fingerprint())
    prior.update({"scope:z-last": "last", "scope:a-first": "first"})
    body = combined_hook_digest(current, json.dumps(prior))
    assert body.index("## a-first") < body.index("## z-last")


def test_unchanged_watcher_response_emits_nothing():
    from io import StringIO
    from types import SimpleNamespace
    from yoke_core.domain.fleet_delta_reports import ReportState, append_steering_reports

    report = CombinedFleetReport(NOW, (ScopedFleetReport("scope", _report(1, NOW)),))
    response = watcher_dict(report, report.fingerprint())
    response["delivered"] = False
    stream = StringIO()
    append_steering_reports(
        ["project"], observed_at=NOW, stream=stream, state=ReportState(),
        call=lambda *_: SimpleNamespace(success=True, result={"settings_json": "{}"}),
        report=response,
    )
    assert stream.getvalue() == ""
