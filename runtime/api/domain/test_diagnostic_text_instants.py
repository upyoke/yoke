"""Refusals and composed evidence keep the exact UTC instant in prose."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.fixtures.session_zones import SESSION_ZONES
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import backlog_github_body_budget as budget
from yoke_core.domain import coordination_claims as claims
from yoke_core.domain import item_status_transitions
from yoke_core.domain import session_launch_native_progress as native
from yoke_core.domain.session_launch_machine_rejections import MachineRejection
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    combined_body,
)
from yoke_core.tools._watch_capture_binding import unwritten_capture_refusal

WIRE = "2026-10-05T00:00:00.123456Z"


@pytest.mark.parametrize("zone", SESSION_ZONES[1:])
def test_diagnostic_text_formats_native_sql_instants(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    point = test_db.execute(
        "SELECT %s::timestamptz", (parse_instant(WIRE),)
    ).fetchone()[0]
    monkeypatch.setattr(
        item_status_transitions,
        "latest_transition",
        lambda *a: {
            "from_status": "idea",
            "to_status": "implementing",
            "created_at": point,
        },
    )
    assert WIRE in budget._evidence_summary(test_db, 1)
    monkeypatch.setattr(
        claims,
        "get_claim",
        lambda *a: SimpleNamespace(
            is_active=False,
            released_at=point,
        ),
    )
    with pytest.raises(claims.CoordinationClaimReleasedError, match=WIRE):
        claims.heartbeat(test_db, 1, now=point)
    launch = SimpleNamespace(
        native_launch_pid=123,
        native_launch_phase="spawn_alive",
        deadline_at=point,
    )
    assert WIRE in native.native_attempt_refusal(launch)
    driver = SimpleNamespace(
        attached_at=point,
        run_id="run",
        phase="waiting",
        session_id="session",
        pid=123,
    )
    assert WIRE in unwritten_capture_refusal(
        Path("/tmp/capture"), grace_seconds=30, driver=driver
    )
    rejection = MachineRejection("machine", "host", ("liveness_expired",), point)
    assert rejection.to_dict()["last_seen_at"] == WIRE
    absent = MachineRejection("machine", "host", (), None)
    assert absent.to_dict()["last_seen_at"] is None
    assert WIRE in combined_body(CombinedFleetReport(composed_at=point, sections=()))
