"""Headlines survive truncated fleet events without creating extra deliveries."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_steering_fleet_report_compose import NOW, _idle, _report
from yoke_core.domain.steering_fleet_report_available import FrontierEntry
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
)
from yoke_core.domain.steering_fleet_report_headline import headline_line
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_questions import OperatorQuestion
from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN


def _combined(*ids, descriptor="alpha · PLAN"):
    entries = tuple(
        FrontierEntry(i, f"work-{i}", "Available work", "implement", i, None, False)
        for i in ids
    )
    report = replace(_report(1, NOW), available=entries)
    return CombinedFleetReport(NOW, (ScopedFleetReport(descriptor, report),))


def test_new_available_counts_use_prior_scope_ids_and_lead_digest():
    before = _combined(1)
    current = _combined(3, 1, 2)
    prior = json.loads(before.fingerprint())
    assert prior["available_ids"] == {"alpha · PLAN": [1]}
    assert json.loads(current.fingerprint())["available_ids"] == {
        "alpha · PLAN": [1, 2, 3]
    }
    assert headline_line(current, prior) == "headline: new available alpha 2"
    assert combined_hook_digest(current, before.fingerprint()).splitlines()[:2] == [
        REPORT_BEGIN,
        "headline: new available alpha 2",
    ]
    assert headline_line(current, {}) == "headline: new available alpha 3"


def test_other_changed_rows_have_no_count_and_identical_report_is_silent():
    before = _combined()
    current = replace(
        before,
        sections=(
            replace(
                before.sections[0], report=replace(_report(1, NOW), idle=(_idle(1),))
            ),
        ),
    )
    body = combined_hook_digest(current, before.fingerprint())
    assert body.splitlines()[1] == "headline: no change"
    assert "2 section(s) unchanged" in body
    assert combined_hook_digest(current, current.fingerprint()) == ""


def test_question_omits_zero_counts():
    combined = replace(
        _combined(),
        questions=(OperatorQuestion(1, "worker", "Worker", "work", "Proceed?", NOW),),
    )
    assert headline_line(combined, {}) == "headline: questions 1"
    assert combined_hook_digest(combined).splitlines()[1] == "headline: questions 1"


def test_actionable_runs_and_recipients_are_distinct_across_scopes():
    report = replace(
        _report(1, NOW),
        deployment_runs=(
            SimpleNamespace(run_id="run", needs_action=True),
            SimpleNamespace(run_id="busy", needs_action=False),
        ),
        undelivered=(
            SimpleNamespace(session_id="worker", needs_seat_action=True),
            SimpleNamespace(session_id="waiting", needs_seat_action=False),
        ),
    )
    combined = CombinedFleetReport(
        NOW,
        (
            ScopedFleetReport("alpha", report),
            ScopedFleetReport("alpha · PLAN", report),
        ),
    )
    assert headline_line(combined, {}) == (
        "headline: runs needing a decision 1 · undelivered 1"
    )


def test_many_scopes_end_with_exact_omitted_count():
    combined = CombinedFleetReport(
        NOW,
        tuple(
            replace(_combined(i).sections[0], descriptor=f"project-{i}")
            for i in range(30)
        ),
    )
    line = headline_line(combined, {})
    assert len(line) < 200
    assert "\n" not in line
    shown = line.count("project-")
    assert line.endswith(f"+{30 - shown} more")


def test_long_descriptor_keeps_the_line_bounded():
    assert headline_line(_combined(1, descriptor="a" * 300), {}) == "headline: +1 more"


@pytest.mark.parametrize("prior", ["", "invalid", "[]", '{"available_ids":null}'])
def test_missing_or_invalid_prior_fingerprint_counts_all_items(prior):
    assert combined_hook_digest(_combined(1, 2), prior).splitlines()[1] == (
        "headline: new available alpha 2"
    )


def test_available_metadata_alone_does_not_create_delivery():
    current = _combined(1)
    prior = json.loads(current.fingerprint())
    del prior["available_ids"]
    assert combined_hook_digest(current, json.dumps(prior)) == ""
