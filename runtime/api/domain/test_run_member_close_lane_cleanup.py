"""A deployment run retires no lanes; the relay on each lane's machine does.

Run settlement closes members without a session, often on a hosted control
plane where no checkout exists. The status write releases the lanes' rows
and claims, and the lanes themselves stay for the standing relay's periodic
sweep on the machine that holds them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.test_run_success_member_settlement import _run
from runtime.api.domain.test_shared_gate_two_phase_settlement import (
    MEMBERS,
    _executing_run,
    _five_ready_members,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain import terminal_lane_cleanup
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.item_worktrees import record_item_worktree
from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION


def _member_lanes(conn: Any, checkout: Path) -> dict[str, int]:
    lanes: dict[str, int] = {}
    for item_id in MEMBERS:
        branch = f"lane-{item_id}"
        path = checkout / ".worktrees" / branch
        path.mkdir(parents=True)
        record_item_worktree(
            conn,
            item_id=item_id,
            branch=branch,
            path=str(path),
            lane_role=LANE_IMPLEMENTATION,
            validate_policy=False,
        )
        lanes[branch] = item_id
    conn.commit()
    return lanes


def test_run_close_out_leaves_member_lanes_to_the_relay_sweep(
    test_db: Any, monkeypatch, tmp_path: Path, capsys
) -> None:
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    lanes = _member_lanes(test_db, tmp_path)
    _executing_run(test_db, "run-lane-cleanup")
    for name in ("cleanup_terminal_item_lanes", "sweep_managed_lanes"):
        monkeypatch.setattr(
            terminal_lane_cleanup,
            name,
            lambda *_a, **_kw: pytest.fail("a run close-out retires no lanes"),
        )

    assert cmd_update("run-lane-cleanup", "status", "succeeded") is None

    assert _run(test_db, "run-lane-cleanup") == ("succeeded", True)
    assert all((tmp_path / ".worktrees" / branch).is_dir() for branch in lanes)
    assert "Lane cleanup warning" not in capsys.readouterr().out
