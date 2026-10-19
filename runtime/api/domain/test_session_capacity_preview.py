"""Capacity rejection retains occupancy without inventing a pool measurement."""

from __future__ import annotations

import io
import json
import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_cli.commands.adapters.session_control_level_placement_output import (
    write_level_candidates,
)
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_placement import place_level
from runtime.api.domain.session_launch_level_test_support import (
    CODEX_SOL,
    LEVEL,
    add_surface,
    level_connection,
    pin_live_workers,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization
from runtime.api.domain.test_session_launch_capacity import _live_session


@pytest.fixture(autouse=True)
def _pool_population(monkeypatch):
    pin_live_workers(monkeypatch, {})


def test_rejected_level_preview_keeps_real_machine_cap_and_unknown_pool_population():
    conn = level_connection(CODEX_SOL)
    add_surface(conn, "machine-1", "codex-cli")
    _live_session(conn, "worker", model="gpt-6.1-sol")
    conn.execute(
        "UPDATE session_relays SET machine_capacity=? WHERE machine_id='machine-1'",
        (
            json.dumps(
                {
                    "max_worker_lanes": 1,
                    "cap_source": "max_worker_lanes",
                    "observed_at": NOW,
                }
            ),
        ),
    )
    placement = place_level(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        level=LEVEL,
        machine_id=None,
        now=parse_instant(NOW),
        eligibility=derive_launch_eligibility,
    )
    assert placement.chosen is None
    candidate = next(c for c in placement.candidates if c.machine_capacity)
    assert candidate.live_workers is None
    payload = candidate.to_dict()
    assert payload["live_workers"] is None
    assert payload["pools"] == []
    (reading,) = payload["machine_capacity"]
    assert (
        reading["machine_id"],
        reading["live_lanes"],
        reading["max_worker_lanes"],
    ) == ("machine-1", 1, 1)
    assert reading["at_capacity"] is True
    output = io.StringIO()
    write_level_candidates(placement.to_dict(), output)
    assert "machine-1: 1/1" in output.getvalue()
    assert "unknown" in output.getvalue()


def test_eligible_option_without_covering_meter_has_unknown_pool_population():
    conn = level_connection(CODEX_SOL)
    add_surface(conn, "machine-1", "codex-cli")
    placement = place_level(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        level=LEVEL,
        machine_id=None,
        now=parse_instant(NOW),
        eligibility=derive_launch_eligibility,
    )
    assert placement.chosen is not None
    assert placement.chosen.live_workers is None
