"""The fleet watch's ``deadlock`` alarm and the report's deadlock section."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from yoke_core.domain.dependency_cycles import DependencyCycle, WaitEdge
from yoke_core.domain.fleet_delta_alarms import DeltaState
from yoke_core.domain.fleet_delta_lines import compare
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, deadlock_rows
from yoke_core.domain.steering_fleet_report_deadlocks import (
    HEADING,
    deadlock_fingerprint,
    deadlock_section,
)

NOW = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc)

CYCLE = DependencyCycle(
    items=("YOK-1", "YOK-2"),
    edges=(
        WaitEdge(11, "YOK-1", "YOK-2", "activation", "status:done"),
        WaitEdge(12, "YOK-2", "YOK-1", "integration", "fact:merged"),
    ),
    stranded=("PLAT-9",),
)


def _snapshot(result: dict) -> FleetSnapshot:
    return FleetSnapshot(
        taken_at=NOW, self_session_id="steerer", deadlocks=deadlock_rows(result)
    )


def test_a_served_loop_alarms_once_and_clears_when_broken():
    state = DeltaState()
    looped = _snapshot({"dependency_cycles": [CYCLE.to_dict()]})

    [alarm] = compare(None, looped, state)
    assert alarm.startswith(
        "fleet ALARM deadlock YOK-1 → YOK-2 → YOK-1: "
        "#11 YOK-1 waits on YOK-2 (activation, status:done); "
        "#12 YOK-2 waits on YOK-1 (integration, fact:merged); strands PLAT-9; "
        "recovery: make one edge in the loop coordination_only"
    )
    assert compare(looped, looped, state) == []
    assert compare(looped, _snapshot({}), state) == ["fleet CLEAR deadlock YOK-1,YOK-2"]


def test_a_build_that_serves_no_cycles_raises_no_deadlock():
    assert deadlock_rows({"ranked_steps": []}) == {}
    assert deadlock_rows({"dependency_cycles": [{"items": []}, "junk"]}) == {}


@dataclass
class _Report:
    deadlocks: tuple = ()


def test_the_report_section_names_each_loop_and_the_recovery():
    assert deadlock_section(_Report()) == []
    lines = deadlock_section(_Report((CYCLE,)))
    assert lines[0] == f"{HEADING}:"
    assert lines[1] == f"  {CYCLE.describe()}"
    assert lines[2].startswith("  recovery: make one edge in the loop")
    assert deadlock_fingerprint(_Report((CYCLE,))) == [("YOK-1,YOK-2", ("11", "12"))]


def test_a_stored_loop_appears_in_the_composed_fleet_report(test_db):
    from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
    from yoke_core.domain.steering_fleet_report_projection import report_dict
    from yoke_core.domain.steering_fleet_report_render import report_body

    conn = seed_steering_scope(test_db)
    for dependent, blocker in ((1, 2), (2, 1), (3, 1)):
        conn.execute(
            "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
            "gate_point, satisfaction, source, rationale, created_at) "
            "VALUES (%s, %s, 'activation', 'status:done', 'operator', '', now())",
            (dependent, blocker),
        )
    conn.commit()

    report = compose(conn)

    [cycle] = report.deadlocks
    assert cycle.items == ("YOK-1", "YOK-2")
    assert cycle.stranded == ("YOK-3",)
    assert report.actionable is True
    assert f"{HEADING}:" in report_body(report)
    assert report_dict(report)["deadlocks"] == [cycle.to_dict()]
