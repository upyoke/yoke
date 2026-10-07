"""Mission scratch on a Test Machine that has no Yoke install.

Preparation and teardown are plain OS commands over the host-command route.
The stale owner-marker removal runs for real against a temporary home whose
PATH carries no ``yoke``; every other argv only records.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from yoke_contracts.machine_qa_host_control import HOST_TEST_COMMAND
from yoke_contracts.qa_mission_scratch import STALE_OWNER_MARKER
from yoke_core.domain.machine_qa_mission_scratch import (
    MissionScratchUnavailableError,
    create_mission_scratch,
    remove_mission_scratch,
)

CURRENT = "01JQ8P4Z9K2M7V6T5R3N1B0CUR"


class _YokeFreeHost:
    """Runs ``/bin/sh`` argv locally under a Yoke-free PATH; others record."""

    def __init__(self, home: Path) -> None:
        self.home = home
        home.mkdir(parents=True)
        self.commands: list[list[str]] = []
        self.env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}

    def run_command(
        self,
        argv: Any,
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        self.commands.append(command)
        if command[0] == "/bin/sh":
            return subprocess.run(
                command, env=self.env, text=True, capture_output=True, timeout=timeout
            )
        returncode = 1 if command[0] == HOST_TEST_COMMAND else 0
        return subprocess.CompletedProcess(command, returncode, "", "")

    @property
    def marker(self) -> Path:
        return self.home / STALE_OWNER_MARKER

    def leave_stale_marker(self, owner: str = "earlier-execution") -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(json.dumps({"owner": owner}))


@pytest.fixture
def host(tmp_path: Path) -> _YokeFreeHost:
    return _YokeFreeHost(tmp_path / "home")


def test_the_host_needs_no_yoke_on_path(host) -> None:
    assert shutil.which("yoke", path=host.env["PATH"]) is None
    host.leave_stale_marker()

    create_mission_scratch(host, execution_id=CURRENT)
    remove_mission_scratch(host, execution_id=CURRENT)

    assert not any(os.path.basename(c[0]) == "yoke" for c in host.commands)
    assert not any("yoke " in " ".join(c) for c in host.commands)


def test_preparation_deletes_a_stale_marker_and_its_otherwise_empty_home(
    host,
) -> None:
    host.leave_stale_marker()

    assert create_mission_scratch(host, execution_id=CURRENT) == {
        "scratch_path": f"/tmp/yoke-qa-mission/{CURRENT}"
    }

    assert not host.marker.exists()
    assert not (host.home / ".yoke").exists()


def test_preparation_keeps_a_yoke_home_that_holds_anything_else(host) -> None:
    host.leave_stale_marker()
    (host.home / ".yoke" / "config.json").write_text("{}")

    create_mission_scratch(host, execution_id=CURRENT)

    assert not host.marker.exists()
    assert (host.home / ".yoke" / "config.json").exists()


def test_a_never_installed_baseline_gains_no_yoke_home(host) -> None:
    create_mission_scratch(host, execution_id=CURRENT)
    result = remove_mission_scratch(host, execution_id=CURRENT)

    assert result["stale_owner_marker_removed"] is True
    assert not (host.home / ".yoke").exists()


def test_teardown_deletes_a_stale_marker_too(host) -> None:
    host.leave_stale_marker()

    result = remove_mission_scratch(host, execution_id=CURRENT)

    assert result["removed"] is True
    assert result["stale_owner_marker_removed"] is True
    assert not host.marker.exists()


def test_an_undeletable_stale_marker_refuses_by_name(host) -> None:
    host.leave_stale_marker()
    (host.home / ".yoke").chmod(0o500)
    try:
        with pytest.raises(MissionScratchUnavailableError) as refusal:
            create_mission_scratch(host, execution_id=CURRENT)
        assert (
            remove_mission_scratch(host, execution_id=CURRENT)[
                "stale_owner_marker_removed"
            ]
            is False
        )
    finally:
        (host.home / ".yoke").chmod(0o700)

    message = str(refusal.value)
    assert "stale_owner_marker_not_removed" in message
    assert "re-run the mission" in message


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
        return {"removed": True, "stale_owner_marker_removed": True}

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
            "--item",
            "ITEM-11",
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
