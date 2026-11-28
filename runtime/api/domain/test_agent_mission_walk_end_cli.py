"""Walk-end only removes its staging and restores the Test Machine."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.posix_mission_operations import (
    posix_mission_scratch_path as mission_scratch_path,
)
from yoke_core.domain import (
    agent_mission_walk_cli,
    machine_qa_mission_walk,
    qa_composed_dispatch,
)

EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"


def _run_walk_end(
    monkeypatch: Any,
    result: dict,
    unrecorded: str | None,
    calls: list[str] | None = None,
) -> int:
    """Run walk-end with fakes; return its exit code."""
    calls = [] if calls is None else calls
    recorded: list[dict] = []
    monkeypatch.setattr(
        agent_mission_walk_cli,
        "resolve_mission_contract",
        lambda parsed, *, prog: {"contract": "issued"},
    )

    def teardown(contract: Any, **_kwargs: Any) -> dict:
        calls.append("teardown")
        return dict(result)

    def record(**kwargs: Any) -> str | None:
        calls.append("record")
        recorded.append(kwargs)
        return unrecorded

    def control_plane(**kwargs: Any) -> None:
        calls.append(kwargs["function_id"])

    monkeypatch.setattr(
        machine_qa_mission_walk, "execute_agent_mission_walk_end", teardown
    )
    monkeypatch.setattr(machine_qa_mission_walk, "record_mission_restore", record)
    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", control_plane)
    exit_code = agent_mission_walk_cli.main(
        ["end", "--item", f"ITEM-{4550}", "--execution-id", EXECUTION_ID]
        + ["--requirement-id", "18152", "--run-id", "991"]
    )
    if result["removed"]:
        [receipt] = recorded
        assert receipt["run_id"] == 991
    else:
        assert recorded == []
    return exit_code


def _walk_result(**overrides: Any) -> dict:
    return {
        "scratch_path": mission_scratch_path(EXECUTION_ID),
        "removed": True,
        "removal_exit_code": 0,
        "removal_stderr": "",
        "stale_owner_marker_removed": True,
        "starting_state_restore": {"restored": True, "baseline": "fresh-host"},
        **overrides,
    }


def test_walk_end_records_the_restore_and_exits_clean(monkeypatch, capsys):
    assert _run_walk_end(monkeypatch, _walk_result(), None) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["starting_state_restore"]["restored"]
    assert "fixture_projects" not in out


def test_walk_end_touches_no_machine_or_project(monkeypatch, capsys):
    calls: list[str] = []

    assert _run_walk_end(monkeypatch, _walk_result(), None, calls=calls) == 0
    # Teardown and the restore receipt are the whole walk-end: no control-plane
    # function retires a Machine or disposes of a project.
    assert calls == ["teardown", "record"]
    assert capsys.readouterr().err == ""


def test_walk_end_names_each_thing_it_could_not_finish(monkeypatch, capsys):
    failed = {
        "restored": False,
        "baseline": "fresh-host",
        "error_code": "starting_state_restore_failed",
        "recovery": "run `yoke test-machine reset --project yoke`",
    }
    result = _walk_result(
        removed=False, stale_owner_marker_removed=False, starting_state_restore=failed
    )

    assert _run_walk_end(monkeypatch, result, None) == 3
    err = capsys.readouterr().err
    assert "mission_scratch_not_removed" in err and "your own walk" in err
    assert "stale_owner_marker_not_removed" in err
    assert "starting_state_restore_failed" in err
    assert "yoke test-machine reset" in err


def test_walk_end_reports_a_restore_receipt_write_failure(monkeypatch, capsys):
    assert _run_walk_end(monkeypatch, _walk_result(), "not_found: run 991") == 3
    assert "starting_state_restore_unrecorded: not_found: run 991" in capsys.readouterr().err


def _fail_walk_end(monkeypatch: Any, error: Exception) -> int:
    monkeypatch.setattr(
        agent_mission_walk_cli,
        "resolve_mission_contract",
        lambda parsed, *, prog: {"contract": "issued"},
    )

    def teardown(contract: Any, **_kwargs: Any) -> dict:
        raise error

    def record(**kwargs: Any) -> None:
        raise AssertionError("a failed teardown records no restore")

    monkeypatch.setattr(
        machine_qa_mission_walk, "execute_agent_mission_walk_end", teardown
    )
    monkeypatch.setattr(machine_qa_mission_walk, "record_mission_restore", record)
    return agent_mission_walk_cli.main(
        ["end", "--item", f"ITEM-{4550}", "--execution-id", EXECUTION_ID]
        + ["--requirement-id", "18152", "--run-id", "991"]
    )


def test_walk_end_names_a_typed_host_control_failure(monkeypatch, capsys):
    error = HostControlLocalError(
        code="baseline_restore_failed",
        phase="baseline_restore",
        detail="restore raised private-detail",
        recovery_hint="Run `yoke test-machine reset --project yoke`.",
        exit_code=7,
        stderr="token=private-stderr",
        stdout="private-stdout",
    )

    assert _fail_walk_end(monkeypatch, error) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == (
        "yoke qa mission walk-end: mission_teardown_failed: "
        "baseline_restore_failed (phase=baseline_restore; exit_code=7). "
        "Recovery: Run `yoke test-machine reset --project yoke`; "
        "then rerun this walk-end."
    )
    assert "private" not in captured.err
    assert "connectivity" not in captured.err


def test_walk_end_keeps_the_generic_refusal_for_untyped_failures(
    monkeypatch, capsys
):
    assert _fail_walk_end(monkeypatch, RuntimeError("private-token")) == 2
    err = capsys.readouterr().err
    assert "mission_teardown_failed (RuntimeError)" in err
    assert "restore host connectivity" in err
    assert "private" not in err
