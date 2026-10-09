"""Project-wide report sections render once per project, not once per seat."""

from __future__ import annotations

import dataclasses

from runtime.api.domain.test_steering_fleet_report_compose import NOW, _report
from yoke_core.domain.delivery_landing_custody import HELD
from yoke_core.domain.fleet_delta_disappearances import shown_rows
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
    combined_body,
    combined_dict,
)
from yoke_core.domain.steering_fleet_report_deployment_runs import (
    DeploymentRunProgress,
)
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_landed_open import LandedItem
from yoke_core.domain.steering_fleet_report_undelivered import UndeliveredMessages

RUN_ID = "run-20260826-001"


def _run() -> DeploymentRunProgress:
    return DeploymentRunProgress(
        run_id=RUN_ID,
        flow="prod-release",
        status="executing",
        stage="item-qa",
        stage_seconds=600,
        outstanding=1,
        total_blocking=2,
        unresolved=(),
        red=(),
        driver_phase="qa",
        member_lines=("member 7: 1 blocker — woken 11:58Z, acknowledged",),
    )


def _landed(item_id: int, ref: str, run_id: str = "") -> LandedItem:
    return LandedItem(
        item_id=item_id,
        public_ref=ref,
        status="release",
        landed_at="2026-08-26T11:00:00.000000Z",
        landed_seconds=3600,
        custody_state=HELD if run_id else "unheld",
        custody_run_id=run_id,
    )


def _undelivered(session_id: str) -> UndeliveredMessages:
    return UndeliveredMessages(
        session_id=session_id,
        delivery_state="never_attempted",
        envelope_count=1,
        oldest_seconds=900,
    )


def _seat(descriptor: str, project_id: int = 1, **rows) -> ScopedFleetReport:
    rows.setdefault("deployment_runs", (_run(),))
    report = dataclasses.replace(_report(project_id, NOW), **rows)
    return ScopedFleetReport(descriptor, report)


def _combined(*sections: ScopedFleetReport) -> CombinedFleetReport:
    return CombinedFleetReport(composed_at=NOW, sections=sections)


def test_three_seats_on_one_project_render_its_run_once() -> None:
    combined = _combined(
        _seat("yoke"),
        _seat("yoke · plan-a"),
        _seat("yoke · plan-b"),
    )
    assert combined_hook_digest(combined).count(RUN_ID) == 1
    assert combined_body(combined).count(f"{RUN_ID}  executing") == 1


def test_seats_on_two_projects_each_keep_their_own_run() -> None:
    combined = _combined(_seat("yoke"), _seat("webapp", project_id=2))
    assert combined_hook_digest(combined).count(f"{RUN_ID}  executing") == 2


def test_landed_and_undelivered_rows_merge_across_seats_once_each() -> None:
    combined = _combined(
        _seat(
            "yoke",
            landed_open=(_landed(1, "YOK-1"),),
            undelivered=(_undelivered("session-a"),),
        ),
        _seat(
            "yoke · plan-a",
            landed_open=(_landed(1, "YOK-1"), _landed(2, "YOK-2")),
            undelivered=(_undelivered("session-a"), _undelivered("session-b")),
        ),
    )
    digest = combined_hook_digest(combined)
    assert digest.count("YOK-1  still release") == 1
    assert digest.count("YOK-2  still release") == 1
    assert digest.count("  session session-a  ") == 1
    assert digest.count("  session session-b  ") == 1
    # The document seat had nothing seat-specific left, so the digest omits
    # its heading; its landed item rendered under the project's first seat.
    assert "## yoke · plan-a" not in digest
    assert digest.index("## yoke") < digest.index("YOK-2")


def test_a_landed_item_a_listed_run_delivers_is_not_repeated() -> None:
    combined = _combined(
        _seat(
            "yoke",
            landed_open=(_landed(1, "YOK-1", RUN_ID), _landed(2, "YOK-2")),
        )
    )
    digest = combined_hook_digest(combined)
    assert "YOK-1" not in digest
    assert "YOK-2  still release" in digest


def test_a_duplicate_seat_does_not_move_the_fingerprint_twice() -> None:
    one = _combined(_seat("yoke"))
    other = _combined(_seat("yoke"), _seat("yoke · plan-a"))
    changed = _combined(
        _seat("yoke"),
        _seat(
            "yoke · plan-a",
            deployment_runs=(dataclasses.replace(_run(), stage="prod"),),
        ),
    )
    # The extra seat adds its own (empty) seat material; the shared run
    # hashes once, from the first seat of the project.
    assert one.fingerprint() != other.fingerprint()
    assert other.fingerprint() == changed.fingerprint()


def test_disappearance_memory_keeps_project_rows_under_the_first_seat() -> None:
    combined = _combined(
        _seat("yoke", landed_open=(_landed(2, "YOK-2"),)),
        _seat("yoke · plan-a", landed_open=(_landed(2, "YOK-2"),)),
    )
    rows = shown_rows(combined_dict(combined), digest=True)
    runs = [key for key in rows if key[1] == "deployment_runs"]
    landed = [key for key in rows if key[1] == "landed_open"]
    assert runs == [("yoke", "deployment_runs", RUN_ID, "")]
    assert landed == [("yoke", "landed_open", "YOK-2", "")]
