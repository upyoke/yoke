"""Release waits stay compact by gate facts; owed close-outs keep their recovery."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from yoke_contracts.hook_context_compose import (
    compose_hook_context,
    REPORT_OMITTED_NOTICE,
)
from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.delivery_landing_custody import HELD, REMERGED, UNDETERMINED
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
)
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder
from yoke_core.domain.steering_fleet_report_landed_gate import (
    AWAITING_RELEASE,
    CLOSE_OUT_READY,
    DELIVERED,
    UNREADABLE,
    LandedGate,
)
from yoke_core.domain.steering_fleet_report_landed_open import (
    LandedItem,
    landed_without_closeout,
)
from yoke_core.domain.steering_fleet_report_render import report_body


NOW = "2026-10-01T18:20:00.000000Z"
IDLE_SECONDS = 20 * 60
FLOW = "hosted-release"
WAITING = LandedGate(AWAITING_RELEASE, flow=FLOW)
OWED = LandedGate(DELIVERED, flow=FLOW)


def landing(number=1, **changes):
    entry = LandedItem(
        item_id=number,
        public_ref=f"TEST-{number}",
        status="release",
        landed_at=NOW,
        landed_seconds=14 * 3600,
        holder_session_id=str(uuid4()),
        holder_parked=True,
        holder_idle_seconds=6 * 3600,
        workflow_id="dash",
        holder_quiet_reason=f"awaiting TEST-{number} delivery: deployment run, "
        "then post-deploy validation and the done close-out",
        completion_flow_available=True,
        delivery_gate=WAITING,
    )
    return replace(entry, **changes)


def report(*entries):
    holders = tuple(
        ClaimHolder(
            session_id=e.holder_session_id,
            item_id=e.item_id,
            public_ref=e.public_ref,
            mode="parked" if e.holder_parked else "dash",
            parked=e.holder_parked,
            last_activity_at=NOW,
            idle_seconds=e.holder_idle_seconds,
            quiet_reason=e.holder_quiet_reason,
        )
        for e in entries
        if e.holder_session_id
    )
    return FleetReport(
        project_id=1,
        composed_at=NOW,
        staffing_after_seconds=300,
        idle_after_seconds=IDLE_SECONDS,
        available=(),
        holders=holders,
        idle=holders,
        undelivered=(),
        unregistered_launches=(),
        landed_open=entries,
        dead_waits=(),
        launchable=(),
        session_counts=(),
    )


@pytest.mark.parametrize(
    "custody, run, expected",
    [
        ("unheld", "", f"awaiting next {FLOW} release (parked)"),
        (HELD, str(uuid4()), f"awaiting {FLOW} release — delivering in"),
        (REMERGED, str(uuid4()), f"awaiting next {FLOW} release — merged again"),
        (UNDETERMINED, "", "release custody unreadable"),
    ],
    ids=["awaiting-enrollment", "delivering", "awaiting-later-candidate", "unread"],
)
def test_parked_release_is_compact_even_after_hours_of_tool_silence(
    custody, run, expected
):
    entry = landing(custody_state=custody, custody_run_id=run)
    body = report_body(report(entry))
    lines = [line for line in body.splitlines() if entry.public_ref in line]
    assert len(lines) == 1
    assert expected in lines[0]
    assert entry.holder_session_id not in body
    assert "idle holders" not in body
    assert "wake `" not in body
    assert "finish close-out" not in body


@pytest.mark.parametrize(
    "changes, context",
    [
        ({"holder_parked": False}, "holder idle 360m"),
        ({"holder_session_id": ""}, "no live holder"),
        (
            {
                "holder_native_process_gone": True,
                "holder_process_phrase": "process gone, claims held",
            },
            "holder process gone, claims held",
        ),
    ],
    ids=["unparked-quiet", "no-holder", "process-gone"],
)
def test_release_wait_is_decided_by_gate_facts_not_holder_posture(changes, context):
    entry = landing(**changes)
    body = report_body(report(entry))
    lines = [line for line in body.splitlines() if entry.public_ref in line]
    assert lines == [f"  {entry.public_ref}  awaiting next {FLOW} release ({context})"]
    assert "wake `" not in body
    assert "merge item" not in body
    assert "finish close-out" not in body
    assert "holder is not driving this" not in body


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"holder_session_id": ""}, "finish close-out"),
        ({"holder_parked": False}, "holder is not driving this"),
        ({}, "holder is not driving this"),
        (
            {
                "holder_native_process_gone": True,
                "holder_process_phrase": "process gone, claims held",
            },
            "process gone, claims held",
        ),
        (
            {
                "holder_native_process_gone": True,
                "holder_process_phrase": "contained by sweep: no_authority",
            },
            "contained by sweep: no_authority",
        ),
        (
            {"holder_native_process_gone": True, "holder_resumable": True},
            "message the holder `yoke say --item",
        ),
        (
            {"delivery_gate": LandedGate(CLOSE_OUT_READY), "holder_parked": False},
            "close-out ready",
        ),
        (
            {"delivery_gate": LandedGate(UNREADABLE, detail="flow unreadable")},
            "delivery gate unreadable — flow unreadable",
        ),
        ({"delivery_gate": WAITING, "status": "implementing"}, "not driving this"),
        (
            {"delivery_gate": WAITING, "completion_flow_available": False},
            "no active completion flow",
        ),
    ],
)
def test_owed_close_outs_keep_detail_and_appear_once(changes, expected):
    entry = landing(**{"delivery_gate": OWED, **changes})
    body = report_body(report(entry))
    assert expected in body
    assert "landed 14h00m ago" in body
    assert sum(entry.public_ref in line for line in body.splitlines()) == 1
    if entry.holder_native_process_gone:
        assert "wake `" not in body


def test_owed_close_out_with_quiet_holder_names_wake_and_close_out():
    entry = landing(delivery_gate=OWED, holder_parked=False)
    body = report_body(report(entry))
    assert f"wake `yoke say --item {entry.public_ref} --stdin`" in body
    assert "finish close-out with `" in body


def test_working_holder_stalls_at_the_existing_idle_threshold():
    entry = landing(
        delivery_gate=OWED, holder_parked=False, holder_idle_seconds=IDLE_SECONDS - 1
    )
    assert "holder is not driving this" not in report_body(report(entry))
    entry = replace(entry, holder_idle_seconds=IDLE_SECONDS)
    assert "holder is not driving this" in report_body(report(entry))
    assert f"yoke say --item {entry.public_ref}" in report_body(report(entry))


@pytest.mark.parametrize("harness", INLINE_CONTEXT_BYTES)
def test_thirteen_release_parks_fit_hook_ceiling_with_a_delivery(harness):
    # The diagnostic live roster on this date contained 13 release parks,
    # quiet for up to six hours, with long post-deploy reasons.
    entries = tuple(landing(number) for number in range(1, 14))
    fleet = report(*entries)
    combined = CombinedFleetReport(NOW, (ScopedFleetReport("yoke", fleet),))
    digest = combined_hook_digest(combined)
    context = compose_hook_context(
        ["Delivered steering message " + "x" * 1024], [], [digest], harness_id=harness
    )
    assert len(context.encode()) <= INLINE_CONTEXT_BYTES[harness]
    assert REPORT_OMITTED_NOTICE not in context
    for entry in entries:
        assert sum(entry.public_ref + " " in line for line in digest.splitlines()) == 1
    assert digest in context
    assert len(report_body(fleet).encode()) < min(INLINE_CONTEXT_BYTES.values())


def test_gate_facts_and_active_flow_decide_the_release_wait(test_db):
    from runtime.api.fixtures.backlog import insert_item

    insert_item(
        test_db,
        id=1,
        title="Awaiting delivery",
        workflow_id="dash",
        status="release",
        merged_at=NOW,
    )
    # The real active-flow query, the shared flow resolution and gate facts.
    stages = [{"name": "deploy", "stage_kind": "execution", "step_runner": "auto"}]
    cmd_create(
        test_db,
        FLOW,
        "yoke",
        FLOW,
        "",
        json.dumps(stages),
        target_tier="persistent",
        environment="development",
    )
    test_db.execute("UPDATE items SET deployment_flow=%s WHERE id=1", (FLOW,))
    # An unparked holder: posture must not change the classification.
    holder = replace(report(landing(holder_parked=False)).holders[0], parked=False)

    def entry(of=holder):
        return landed_without_closeout(test_db, project_id=1, now=NOW, holders=(of,))[0]

    assert entry().delivery_gate == WAITING
    assert entry().awaiting_release
    test_db.execute(
        "UPDATE deployment_flows SET status='disabled' WHERE id=%s", (FLOW,)
    )
    assert entry().delivery_gate == WAITING
    assert not entry().awaiting_release
    test_db.execute(
        "UPDATE deployment_flows SET status='active', target_tier=NULL, "
        "target_environment_id=NULL WHERE id=%s",
        (FLOW,),
    )
    assert entry().delivery_gate.state == CLOSE_OUT_READY
    assert not entry().awaiting_release
    dead = replace(holder, native_process_gone_at=NOW)
    assert entry(dead).holder_native_process_gone
