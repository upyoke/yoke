"""Delivery parks stay compact, while actionable landings retain their recovery."""

from dataclasses import replace
from uuid import uuid4

import pytest

from yoke_contracts.hook_context_compose import (
    compose_hook_context,
    REPORT_OMITTED_NOTICE,
)
from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_core.domain.delivery_landing_custody import HELD, REMERGED, UNDETERMINED
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
)
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder
from yoke_core.domain.steering_fleet_report_landed_open import (
    LandedItem,
    landed_without_closeout,
)
from yoke_core.domain.steering_fleet_report_render import report_body


NOW = "2026-10-01T18:20:00Z"
IDLE_SECONDS = 20 * 60


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
        ("unheld", "", "awaiting deployment run"),
        (HELD, str(uuid4()), "delivering in"),
        (REMERGED, str(uuid4()), "awaiting deployment run"),
    ],
    ids=["awaiting-enrollment", "delivering", "awaiting-later-candidate"],
)
def test_parked_release_is_compact_even_after_hours_of_tool_silence(
    custody, run, expected
):
    entry = landing(custody_state=custody, custody_run_id=run)
    body = report_body(report(entry))
    lines = [line for line in body.splitlines() if entry.public_ref in line]
    assert len(lines) == 1
    assert expected in lines[0]
    assert "(parked)" in lines[0]
    assert entry.holder_session_id not in body
    assert "idle holders" not in body
    assert "wake `" not in body
    assert "finish close-out" not in body


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"holder_session_id": ""}, "finish close-out"),
        ({"holder_parked": False}, "holder is not driving this"),
        ({"status": "implementing"}, "holder is not driving this"),
        ({"custody_state": UNDETERMINED}, "release custody unreadable"),
        ({"completion_flow_available": False}, "no active completion flow"),
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
    ],
)
def test_actionable_landings_keep_detail_and_appear_once(changes, expected):
    entry = landing(**changes)
    body = report_body(report(entry))
    assert expected in body
    assert "landed 14h00m ago" in body
    assert sum(entry.public_ref in line for line in body.splitlines()) == 1
    if entry.holder_native_process_gone:
        assert "wake `" not in body


def test_working_holder_stalls_at_the_existing_idle_threshold():
    entry = landing(holder_parked=False, holder_idle_seconds=IDLE_SECONDS - 1)
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


def test_resolved_active_flow_and_process_observation_decide_compaction(test_db):
    from runtime.api.fixtures.backlog import insert_item

    insert_item(
        test_db,
        id=1,
        title="Awaiting delivery",
        workflow_id="dash",
        status="release",
        merged_at=NOW,
    )
    # Use the real active-flow query and the shared batched resolution surface.
    flow = test_db.execute(
        "SELECT id FROM deployment_flows WHERE project_id=1 AND status='active' LIMIT 1"
    ).fetchone()
    if flow is None:
        test_db.execute(
            "INSERT INTO deployment_flows (id, project_id, name, stages, created_at, status) VALUES ('delivery', 1, 'Delivery', '[]', %s, 'active')",
            (NOW,),
        )
        flow_id = "delivery"
    else:
        flow_id = str(flow[0])
    test_db.execute("UPDATE items SET deployment_flow=%s WHERE id=1", (flow_id,))
    holder = report(landing()).holders[0]
    entries = landed_without_closeout(test_db, project_id=1, now=NOW, holders=(holder,))
    assert entries[0].delivery_wait
    test_db.execute(
        "UPDATE deployment_flows SET status='disabled' WHERE id=%s", (flow_id,)
    )
    assert not landed_without_closeout(
        test_db, project_id=1, now=NOW, holders=(holder,)
    )[0].delivery_wait
    dead = replace(holder, native_process_gone_at=NOW)
    assert landed_without_closeout(test_db, project_id=1, now=NOW, holders=(dead,))[
        0
    ].holder_native_process_gone
