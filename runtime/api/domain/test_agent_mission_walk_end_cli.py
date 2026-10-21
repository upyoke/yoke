"""Walk-end's exit status names every teardown step it could not finish."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain import (
    agent_mission_project_disposal,
    agent_mission_walk_cli,
    machine_qa_mission_walk,
)

EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"


NO_PROJECTS = {"host_projects": [], "error": None}


def _run_walk_end(
    monkeypatch: Any,
    result: dict,
    unrecorded: str | None,
    disposal: tuple[list[str], list[str], bool] = ([], [], True),
    fixture_projects: dict = NO_PROJECTS,
    calls: list[str] | None = None,
) -> int:
    """Run walk-end with fakes; return its exit code and the steps it took."""
    calls = [] if calls is None else calls
    recorded: list[dict] = []
    disposals: list[dict] = []
    monkeypatch.setattr(
        agent_mission_walk_cli,
        "resolve_mission_contract",
        lambda parsed, *, prog: {"contract": "issued"},
    )

    def uninstall(contract: Any, *, timeout_seconds: int) -> dict:
        calls.append("uninstall")
        return fixture_projects

    def teardown(contract: Any, *, timeout_seconds: int) -> dict:
        calls.append("restore")
        return dict(result)

    monkeypatch.setattr(
        machine_qa_mission_walk, "execute_agent_mission_project_uninstall", uninstall
    )
    monkeypatch.setattr(
        machine_qa_mission_walk, "execute_agent_mission_walk_end", teardown
    )

    def record(**kwargs: Any) -> str | None:
        recorded.append(kwargs)
        return unrecorded

    monkeypatch.setattr(machine_qa_mission_walk, "record_mission_restore", record)

    def dispose(**kwargs: Any) -> tuple[list[str], list[str], bool]:
        calls.append("dispose")
        disposals.append(kwargs)
        return list(disposal[0]), list(disposal[1]), disposal[2]

    monkeypatch.setattr(
        agent_mission_project_disposal, "request_project_disposal", dispose
    )
    exit_code = agent_mission_walk_cli.main(
        ["end", "--item", f"ITEM-{4550}", "--execution-id", EXECUTION_ID]
        + ["--requirement-id", "18152", "--run-id", "991"]
    )
    if fixture_projects["error"]:
        assert calls == ["uninstall"]
    else:
        assert disposals[0]["run_id"] == 991
        assert disposals[0]["host_projects"] == fixture_projects["host_projects"]
        # Disposal settles before the restore can erase the host evidence.
        assert calls[:2] == ["uninstall", "dispose"]
    if "restore" in calls:
        assert recorded and recorded[0]["run_id"] == 991
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
    assert json.loads(capsys.readouterr().out)["starting_state_restore"]["restored"]


def test_walk_end_names_each_thing_it_could_not_finish(monkeypatch, capsys):
    failed = {
        "restored": False,
        "baseline": "fresh-host",
        "error_code": "starting_state_restore_failed",
        "recovery": "run `yoke test-machine reset --project yoke`",
    }
    result = _walk_result(removed=False, starting_state_restore=failed)

    assert _run_walk_end(monkeypatch, result, "not_found: run 991") == 3
    err = capsys.readouterr().err
    assert "mission_scratch_not_removed" in err and "your own walk" in err
    assert "starting_state_restore_failed" in err
    assert "yoke test-machine reset" in err
    assert "starting_state_restore_unrecorded: not_found: run 991" in err


HOST_PROJECT = {
    "project_id": 41,
    "checkout": "/Users/tester/code/cedar",
    "uninstalled": True,
    "reason": None,
}
WITH_PROJECT = {"host_projects": [HOST_PROJECT], "error": None}


def test_walk_end_hands_the_host_projects_to_disposal(monkeypatch, capsys):
    exit_code = _run_walk_end(
        monkeypatch, _walk_result(), None, fixture_projects=WITH_PROJECT
    )

    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fixture_projects"]["host_projects"] == [HOST_PROJECT]


def test_a_recorded_but_unsettled_disposal_still_restores_and_fails(
    monkeypatch, capsys
):
    blocked = "fixture_project_not_disposed: project cedar is blocked"

    exit_code = _run_walk_end(
        monkeypatch,
        _walk_result(),
        None,
        disposal=([blocked], [], True),
        fixture_projects=WITH_PROJECT,
    )

    assert exit_code == 3
    assert blocked in capsys.readouterr().err


def test_an_unrecorded_disposal_leaves_the_host_unrestored(monkeypatch, capsys):
    failed = "fixture_project_disposal_failed: control plane unreachable"
    calls: list[str] = []

    exit_code = _run_walk_end(
        monkeypatch,
        _walk_result(),
        None,
        disposal=([failed], [], False),
        fixture_projects=WITH_PROJECT,
        calls=calls,
    )

    assert exit_code == 3
    assert calls == ["uninstall", "dispose"]
    err = capsys.readouterr().err
    assert failed in err and "fixture_project_disposal_unrecorded" in err


def test_walk_end_names_an_unreadable_host_config_without_disposing(
    monkeypatch, capsys
):
    unreadable = "fixture_projects_unreadable: ~/.yoke/config.json is not JSON"
    projects = {"host_projects": [], "error": unreadable}

    exit_code = _run_walk_end(
        monkeypatch, _walk_result(), None, fixture_projects=projects
    )

    assert exit_code == 3
    assert unreadable in capsys.readouterr().err


def test_a_project_left_for_an_administrator_is_named_but_never_blocks(
    monkeypatch, capsys
):
    notice = "fixture_project_left_for_administrator: project cedar"

    exit_code = _run_walk_end(
        monkeypatch,
        _walk_result(),
        None,
        disposal=([], [notice], True),
        fixture_projects=WITH_PROJECT,
    )

    assert exit_code == 0
    assert notice in capsys.readouterr().err
