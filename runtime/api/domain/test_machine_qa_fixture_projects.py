"""Walk-end finds the projects its Test Machine registers and uninstalls them."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_core.domain.machine_qa_fixture_projects import (
    HOST_GIT,
    FixtureProjectDiscoveryError,
    discover_host_projects,
    uninstall_host_projects,
)

CONFIG = "/Users/tester/.yoke/config.json"
CHECKOUT = "/Users/tester/code/cedar"
LANE = "/Users/tester/code/cedar/.worktrees/CED-1"


def _config(**projects: list[dict]) -> str:
    return json.dumps(
        {
            "active_env": "prod",
            "connections": {
                "prod": {"transport": "https", "api_url": "https://example.test"}
            },
            "connection_projects": projects,
        }
    )


class _InstalledHost(FakeHostControl):
    """A host where one walk installed cedar and opened a lane in it."""

    def __init__(self, *, uninstall_exit: int = 0) -> None:
        super().__init__()
        self.files[CONFIG] = _config(
            prod=[{"checkout": CHECKOUT, "project_id": 41}],
            stage=[{"checkout": "/Users/tester/code/other", "project_id": 7}],
        )
        self.uninstall_exit = uninstall_exit

    def run_command(self, argv: Any, **_kwargs: Any) -> Any:
        command = list(argv)
        self.commands.append(command)
        stdout, code = "", 0
        if command[3:5] == ["worktree", "list"]:
            stdout = f"worktree {CHECKOUT}\nHEAD abc\n\nworktree {LANE}\nHEAD def\n"
        elif command[1:3] == ["project", "uninstall"]:
            code = self.uninstall_exit
        return subprocess.CompletedProcess(command, code, stdout, "")


def test_a_host_without_yoke_registers_nothing() -> None:
    assert discover_host_projects(FakeHostControl()) == []


def test_discovery_reads_only_the_hosts_active_connection() -> None:
    assert discover_host_projects(_InstalledHost()) == [
        {"checkout": CHECKOUT, "project_id": 41}
    ]


def test_an_unreadable_config_names_its_recovery() -> None:
    host = FakeHostControl()
    host.files[CONFIG] = "{not json"

    with pytest.raises(FixtureProjectDiscoveryError) as refusal:
        discover_host_projects(host)

    assert "fixture_projects_unreadable" in str(refusal.value)
    assert "rerun this walk-end" in str(refusal.value)


def test_uninstall_removes_lanes_before_the_installed_layer() -> None:
    host = _InstalledHost()

    [result] = uninstall_host_projects(host, timeout_seconds=60)

    assert result["uninstalled"] is True
    assert result["removed_worktrees"] == [LANE]
    remove = [HOST_GIT, "-C", CHECKOUT, "worktree", "remove", "--force", "--force"]
    assert host.commands[1] == [*remove, LANE]
    assert host.commands[2] == [HOST_GIT, "-C", CHECKOUT, "worktree", "prune"]
    assert host.commands[3][1:] == ["project", "uninstall", "--json", CHECKOUT]


def test_a_refused_uninstall_is_named_on_the_result() -> None:
    [result] = uninstall_host_projects(
        _InstalledHost(uninstall_exit=1), timeout_seconds=60
    )

    assert result["uninstalled"] is False
    assert result["reason"] == "uninstall_failed"
    assert result["project_id"] == 41
