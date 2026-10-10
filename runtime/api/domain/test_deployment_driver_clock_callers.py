"""Run-driver authority and release routes consume native clocks on PostgreSQL."""

import pytest

from runtime.api.domain import test_qa_operator_waiver_authority as waivers
from runtime.api.domain.test_qa_operator_waiver_authority import (
    waiver_world as waiver_world,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_helpers, yoke_function_dispatch_qa_claims
from yoke_core.domain.handlers.deployment_run_execution import require_run_driver
from yoke_core.engines.runs_release_handoff import _live_driver


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
@pytest.mark.parametrize("microsecond", [0, 123456])
def test_real_driver_callers_preserve_native_clock(
    waiver_world, monkeypatch, zone, microsecond
):
    conn, requirement_id, _ = waiver_world
    clock = parse_instant("1970-01-01T05:29:59+05:30").replace(microsecond=microsecond)
    monkeypatch.setattr(db_helpers, "utc_now", lambda: clock)
    conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    conn.commit()
    waivers._drive(conn, waivers.RECORDER, now=clock)
    request = waivers._request(requirement_id)
    assert require_run_driver(request, waivers.RUN_ID) is None
    assert yoke_function_dispatch_qa_claims._operator_waiver_allowed(
        request, waivers.MEMBER
    )
    assert _live_driver(conn, waivers.RUN_ID) == waivers.RECORDER
    assert conn.execute("SHOW TimeZone").fetchone()[0] == zone
