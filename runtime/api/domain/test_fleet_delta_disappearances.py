"""Only previously displayed rows receive one grounded disappearance line."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.fleet_delta_disappearances import disappeared_lines, shown_rows
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, SessionRow
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
REF = "held-candidate"
HOLDER = {
    "public_ref": REF,
    "item_id": 42,
    "session_id": "worker",
    "idle_seconds": 1800,
}
LANDING = {
    "public_ref": REF,
    "pr_number": "17",
    "merged": False,
    "closed": False,
    "narrative": "pull request 17 still waiting on checks",
}


def report(**fields):
    return {
        "scopes": [
            {
                "descriptor": "project · plan",
                "idle_after_seconds": 1200,
                "holders": [HOLDER],
                **fields,
            }
        ]
    }


def removed(before, after, snapshot=None):
    return disappeared_lines(
        shown_rows(before, digest=True), shown_rows(after, digest=True), after, snapshot
    )


def test_active_holder_removes_landing_once_with_last_observed_check_context():
    before = report(landings=[LANDING])
    after = report(holders=[{**HOLDER, "idle_seconds": 0}], landings=[])
    lines = removed(before, after)
    assert len(lines) == 1
    assert "no longer listed — worker active again" in lines[0]
    assert "last observed pull request 17 still waiting on checks" in lines[0]
    assert removed(after, after) == []
    assert removed(before, before) == []


@pytest.mark.parametrize(
    "field,reason",
    [("merged", "pull request merged"), ("closed", "pull request closed")],
)
def test_a_previously_observed_terminal_pull_request_names_its_reason(field, reason):
    before = report(landings=[{**LANDING, field: True}])
    assert reason in removed(before, report(landings=[]))[0]


def test_landed_item_proves_a_removed_pull_request_merged():
    before = report(landings=[LANDING])
    assert (
        "pull request merged"
        in removed(before, report(landings=[], landed_open=[{"public_ref": REF}]))[0]
    )


@pytest.mark.parametrize(
    "section",
    [
        "idle",
        "in_flight",
        "suspected_orphaned_waiters",
        "landed_open",
        "dead_waits",
        "vendor_errors",
        "stranded",
    ],
)
def test_every_holder_section_names_released_claims(section):
    before = report(**{section: [HOLDER]})
    assert "claim released" in removed(before, report(holders=[]))[0]


def test_finished_run_is_reported_once_and_not_called_successful():
    before = report(deployment_runs=[{"run_id": "run-one", "status": "executing"}])
    after = report(deployment_runs=[])
    assert "run finished (no longer live)" in removed(before, after)[0]
    assert removed(after, after) == []


def test_missing_run_projection_does_not_invent_completion():
    before = report(deployment_runs=[{"run_id": "run-one"}])
    assert "run state unavailable" in removed(before, report())[0]


def test_scope_removal_does_not_invent_released_claim_or_finished_run():
    before = report(idle=[HOLDER], deployment_runs=[{"run_id": "run-one"}])
    assert all(
        "scope no longer held" in line for line in removed(before, {"scopes": []})
    )


def test_holder_moving_into_a_long_call_names_the_new_section():
    before = report(idle=[HOLDER])
    assert (
        "holder now inside a long-running call"
        in removed(before, report(in_flight=[HOLDER]))[0]
    )


def test_roster_activity_explains_a_removed_landing_without_holder_projection():
    snapshot = FleetSnapshot(
        NOW,
        "seat",
        sessions={
            "worker": SessionRow(
                "worker",
                "codex-cli",
                "dash",
                False,
                False,
                False,
                NOW - timedelta(seconds=5),
                claimed_items=(REF,),
            )
        },
    )
    before = report(landings=[LANDING])
    before["scopes"][0]["landings"][0] = {**LANDING, "session_id": "worker"}
    after = report(landings=[])
    del after["scopes"][0]["holders"]
    assert "worker active again" in removed(before, after, snapshot)[0]


def test_unproven_cause_is_named_with_a_reachable_inspection_command():
    before = report(landings=[LANDING])
    after = report(landings=[])
    line = removed(before, after)[0]
    assert "current cause unavailable" in line
    assert "yoke steering report get" in line


def test_capped_rows_not_shown_are_not_later_reported_as_removed():
    rows = [
        {**LANDING, "public_ref": f"candidate-{index}"}
        for index in range(SECTION_LIMIT + 1)
    ]
    before = report(landings=rows)
    assert len(shown_rows(before, digest=True)) == SECTION_LIMIT
    assert all(
        f"candidate-{SECTION_LIMIT} [" not in line
        for line in removed(before, report(landings=[]))
    )


def test_row_moved_beyond_cap_is_not_falsely_called_released():
    before = report(landings=[LANDING])
    rows = [
        {**LANDING, "public_ref": f"candidate-{index}"}
        for index in range(SECTION_LIMIT)
    ]
    assert (
        "outside the displayed section limit"
        in removed(before, report(landings=[*rows, LANDING]))[0]
    )


def test_digest_does_not_remember_inventory_or_suppressed_idle_rows():
    assert shown_rows(report(), digest=True) == {}
    assert len(shown_rows(report(), digest=False)) == 1
    before = report(idle=[HOLDER], landed_open=[HOLDER])
    assert {row.section for row in shown_rows(before, digest=True).values()} == {
        "landed_open"
    }


@pytest.mark.parametrize("section", ["deployment_runs", "landed_open"])
def test_project_rows_do_not_disappear_when_actionable_seats_reorder(section):
    row = {"run_id": "run-one"} if section == "deployment_runs" else HOLDER
    seats = [
        {"descriptor": name, "project_id": 1, section: [row]}
        for name in ("project · a", "project · b")
    ]
    before = {"scopes": seats}
    after = {"scopes": list(reversed(seats))}
    assert len(shown_rows(before, digest=True)) == 1
    assert removed(before, after) == []
    assert (
        len(
            removed(
                before, {"scopes": [{**seat, section: []} for seat in reversed(seats)]}
            )
        )
        == 1
    )


def test_project_landed_union_is_capped_once_and_covered_runs_are_suppressed():
    seats = [
        {
            "descriptor": "project · b",
            "project_id": 1,
            "deployment_runs": [{"run_id": "run-one"}],
            "landed_open": [{**HOLDER, "custody_run_id": "run-one"}],
        },
        {
            "descriptor": "project · a",
            "project_id": 1,
            "landed_open": [
                {**HOLDER, "public_ref": f"candidate-{i}"}
                for i in range(SECTION_LIMIT + 1)
            ],
        },
    ]
    rows = shown_rows({"scopes": seats}, digest=True)
    assert len(rows) == SECTION_LIMIT + 1
    assert all(row.subject != REF for row in rows.values())
