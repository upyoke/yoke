"""A deployment run retires its members' lanes with one sweep per checkout.

Run settlement closes members without a session and never retires a
member's lanes inline: the status write already released their rows and
claims. After every member closes, the run reads each closed item's project
to find this machine's checkout and target branch, and sweeps each distinct
checkout once. What the sweep could not retire, or a member whose checkout
it could not reach, is printed on the run's output with the recovery that
frees it, and never holds the run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION
from yoke_core.domain.worktree_capacity import DOCTOR_RETIRE_RECIPE


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


def _wire_sweep(
    monkeypatch, checkout: Path, *, preserved: tuple[str, ...] = ()
) -> dict[str, list[Any]]:
    """Point the sweep at *checkout*, recording per-item cleanup and sweeps."""
    calls: dict[str, list[Any]] = {"item_cleanups": [], "swept": []}

    def _item_cleanup(item, **_kw):
        calls["item_cleanups"].append(item.get("public_ref"))
        return terminal_lane_cleanup.TerminalLaneCloseOut()

    def _sweep(**kwargs) -> tuple[tuple[str, ...], dict[str, Any]]:
        calls["swept"].append((str(kwargs["repo_root"]), kwargs["target"]))
        return preserved, {}

    monkeypatch.setattr(
        terminal_lane_cleanup, "cleanup_terminal_item_lanes", _item_cleanup
    )
    monkeypatch.setattr(terminal_lane_cleanup, "sweep_managed_lanes", _sweep)
    monkeypatch.setattr(
        terminal_lane_cleanup,
        "checkout_for_project_id",
        lambda project_id: checkout if project_id is not None else None,
    )
    return calls


def test_run_close_out_sweeps_each_checkout_once_without_per_member_retirement(
    test_db: Any, monkeypatch, tmp_path: Path
) -> None:
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _member_lanes(test_db, tmp_path)
    _executing_run(test_db, "run-lane-cleanup")
    calls = _wire_sweep(monkeypatch, tmp_path)

    assert cmd_update("run-lane-cleanup", "status", "succeeded") is None

    assert _run(test_db, "run-lane-cleanup") == ("succeeded", True)
    assert len(MEMBERS) > 1
    assert calls["item_cleanups"] == []
    assert calls["swept"] == [(str(tmp_path.resolve()), "main")]


def test_a_sweep_warning_is_printed_on_the_run_output(
    test_db: Any, monkeypatch, tmp_path: Path, capsys
) -> None:
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _member_lanes(test_db, tmp_path)
    _executing_run(test_db, "run-lane-kept")
    warning = "machine-wide merged-lane sweep stopped after an unexpected refusal"
    _wire_sweep(monkeypatch, tmp_path, preserved=(warning,))

    assert cmd_update("run-lane-kept", "status", "succeeded") is None

    output = capsys.readouterr().out
    assert _run(test_db, "run-lane-kept") == ("succeeded", True)
    assert output.count(f"Lane cleanup warning: {warning}") == 1


def test_a_machine_without_the_checkout_says_so_on_the_run_output(
    test_db: Any, monkeypatch, tmp_path: Path, capsys
) -> None:
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _member_lanes(test_db, tmp_path)
    _executing_run(test_db, "run-no-checkout")
    monkeypatch.setattr(
        terminal_lane_cleanup, "checkout_for_project_id", lambda _project_id: None
    )

    assert cmd_update("run-no-checkout", "status", "succeeded") is None

    output = capsys.readouterr().out
    assert _run(test_db, "run-no-checkout") == ("succeeded", True)
    for item_id in MEMBERS:
        ref = render_item_ref(test_db, item_id)
        assert (
            f"Lane cleanup warning: {ref}: lane sweep skipped: "
            "checkout unavailable on this machine"
        ) in output
    assert DOCTOR_RETIRE_RECIPE in output
