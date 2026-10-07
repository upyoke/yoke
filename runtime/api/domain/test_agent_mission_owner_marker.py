"""A leased host's test-project owner marker outlives no finished execution.

The host scripts run for real against a temporary home, with a stub ``yoke``
on PATH standing in for the host's own control plane.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from yoke_contracts.machine_qa_host_control import HOST_TEST_COMMAND
from yoke_contracts.qa_project_ownership import OWNER_FILE
from yoke_core.domain.machine_qa_mission_scratch import (
    MissionScratchUnavailableError,
    create_mission_scratch,
)

FINISHED = "01JQ8P4Z9K2M7V6T5R3N1B0FIN"
LIVE = "01JQ8P4Z9K2M7V6T5R3N1B0LIV"
CURRENT = "01JQ8P4Z9K2M7V6T5R3N1B0CUR"

_STUB_YOKE = """#!/usr/bin/env python3
import json, sys
print(json.dumps({"success": True, "result": {"rows": []}}))
"""


class _ScriptHost:
    """Runs ``python3 -c`` host scripts locally; other argv only records."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.commands: list[list[str]] = []
        bin_dir = home / "bin"
        bin_dir.mkdir(parents=True)
        stub = bin_dir / "yoke"
        stub.write_text(_STUB_YOKE)
        stub.chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        }

    def run_command(
        self,
        argv: Any,
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        self.commands.append(command)
        if command[:2] == ["python3", "-c"]:
            return subprocess.run(
                [sys.executable, *command[1:]],
                env=self.env,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        returncode = 1 if command[0] == HOST_TEST_COMMAND else 0
        return subprocess.CompletedProcess(command, returncode, "", "")

    @property
    def marker(self) -> Path:
        return self.home / ".yoke" / OWNER_FILE

    def mark(self, owner: str) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(json.dumps({"owner": owner}))


@pytest.fixture
def host(tmp_path: Path) -> _ScriptHost:
    return _ScriptHost(tmp_path / "home")


def _states(**states: str):
    terminal = {"completed", "aborted", "error"}
    asked: list[str] = []

    def lookup(owner: str) -> dict[str, Any]:
        asked.append(owner)
        state = states.get(owner)
        return {"state": state, "terminal": state in terminal}

    lookup.asked = asked  # type: ignore[attr-defined]
    return lookup


def test_preparation_replaces_a_finished_owner_and_records_it(host) -> None:
    host.mark(FINISHED)
    lookup = _states(**{FINISHED: "completed"})

    scratch = create_mission_scratch(host, execution_id=CURRENT, owner_state=lookup)

    replaced = scratch["owner_marker"]["replaced_finished_owner"]
    assert lookup.asked == [FINISHED]
    assert replaced["execution_id"] == FINISHED
    assert replaced["state"] == "completed"
    assert replaced["teardown"]["project_cleanup_ok"] is True
    assert replaced["teardown"]["project_cleanup"]["owner_marker_removed"] is True
    assert ["/bin/rm", "-rf", replaced["teardown"]["scratch_path"]] in host.commands
    assert json.loads(host.marker.read_text())["owner"] == CURRENT


def test_preparation_still_refuses_a_live_owner(host) -> None:
    host.mark(LIVE)

    with pytest.raises(MissionScratchUnavailableError) as refusal:
        create_mission_scratch(
            host, execution_id=CURRENT, owner_state=_states(**{LIVE: "running"})
        )

    message = str(refusal.value)
    assert "qa_project_owner_conflict" in message
    assert LIVE in message and "running" in message
    assert json.loads(host.marker.read_text())["owner"] == LIVE


def test_an_owner_the_control_plane_does_not_know_is_never_replaced(host) -> None:
    host.mark(LIVE)

    with pytest.raises(MissionScratchUnavailableError, match="is unknown"):
        create_mission_scratch(host, execution_id=CURRENT, owner_state=_states())

    assert json.loads(host.marker.read_text())["owner"] == LIVE


def test_without_a_control_plane_answer_the_conflict_refuses_by_name(host) -> None:
    host.mark(FINISHED)

    with pytest.raises(MissionScratchUnavailableError, match="cannot ask"):
        create_mission_scratch(host, execution_id=CURRENT)

    assert json.loads(host.marker.read_text())["owner"] == FINISHED


def test_a_continued_walk_inherits_its_predecessor_without_teardown(host) -> None:
    host.mark(FINISHED)
    lookup = _states(**{FINISHED: "aborted"})

    scratch = create_mission_scratch(
        host,
        execution_id=CURRENT,
        continues_execution_id=FINISHED,
        owner_state=lookup,
    )

    assert lookup.asked == []
    assert scratch["owner_marker"]["replaced_finished_owner"] is None
    assert scratch["owner_marker"]["inherited_owners"] == [FINISHED]
    assert json.loads(host.marker.read_text()) == {
        "owner": CURRENT,
        "inherited_owners": [FINISHED],
    }
    assert not any(command[0] == "/bin/rm" for command in host.commands)


def test_review_submission_tears_down_each_live_mission_first(
    monkeypatch: Any, capsys: Any
) -> None:
    from types import SimpleNamespace

    from yoke_core.domain import (
        machine_qa_host_control,
        machine_qa_local_execution,
        qa_composed_dispatch,
        qa_plan_review_cli,
    )

    calls: list[tuple[str, Any]] = []

    def dispatch(*, function_id, target, payload, actor):
        calls.append((function_id, payload.get("requirement_id")))
        if function_id == "test_machine.mission.access":
            if payload["requirement_id"] == 7:
                return SimpleNamespace(
                    success=True, result={"execution": {"mission": 7}}
                )
            return SimpleNamespace(success=False, result=None)
        raise AssertionError(function_id)

    def teardown(contract):
        calls.append(("teardown", contract["mission"]))
        return {"removed": True, "project_cleanup_ok": True}

    def submit(**kwargs):
        calls.append((kwargs["function_id"], None))
        return {"submission": "persisted"}

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", dispatch)
    monkeypatch.setattr(
        machine_qa_local_execution, "execute_agent_mission_scratch_teardown", teardown
    )
    monkeypatch.setattr(
        machine_qa_host_control, "register_test_machine_host_control", lambda: None
    )
    monkeypatch.setattr(qa_plan_review_cli, "_call_plan_function", submit)
    monkeypatch.setattr(
        "sys.stdin",
        SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "verdicts": [
                        {"requirement_id": 7, "verdict": "pass", "rationale": "ok"},
                        {"requirement_id": 8, "verdict": "pass", "rationale": "ok"},
                    ]
                }
            )
        ),
    )

    exit_code = qa_plan_review_cli.run(
        [
            "--item-id",
            "11",
            "--execution-id",
            CURRENT,
            "--bundle-id",
            "b",
            "--bundle-digest",
            "d",
            "--stdin",
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("test_machine.mission.access", 7),
        ("teardown", 7),
        ("test_machine.mission.access", 8),
        ("qa.plan_review.submit", None),
    ]
    assert "mission_teardown_incomplete" not in capsys.readouterr().err
