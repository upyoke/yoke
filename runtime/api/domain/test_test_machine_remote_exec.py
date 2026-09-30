"""`yoke test-machine exec` reaches a Test Mac without the operator's ~/.ssh."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_cli.commands.adapters import test_machine_exec as adapter
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_harness.test_machine_remote_exec import (
    RemoteExecRefusal,
    known_hosts_path,
    remote_exec_argv,
    run_remote_command,
)


HOST = "test-mac.example.ts.net"
USER = "tester"
AGENT = {"SSH_AUTH_SOCK": "/tmp/agent.sock"}


def _runner(returncode: int, calls: list[list[str]]):
    def run(argv: list[str], check: bool) -> subprocess.CompletedProcess:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode)

    return run


def test_argv_skips_ssh_config_and_pins_keys_under_the_yoke_home(tmp_path) -> None:
    argv = remote_exec_argv(
        host=HOST,
        user=USER,
        known_hosts=known_hosts_path(tmp_path),
        command=["uname", "-a"],
    )

    assert argv[:3] == ["ssh", "-F", "/dev/null"]
    assert f"UserKnownHostsFile={tmp_path}/test-machine/known_hosts" in argv
    assert "IdentityFile=none" in argv
    assert "StrictHostKeyChecking=accept-new" in argv
    # `--` ends ssh's own options, so a command word like `-a` is never
    # re-read as an ssh flag.
    assert argv[-4:] == ["--", f"{USER}@{HOST}", "uname", "-a"]


def test_exit_status_passes_through_and_the_known_hosts_home_exists(
    tmp_path,
) -> None:
    calls: list[list[str]] = []

    code = run_remote_command(
        host=HOST,
        user=USER,
        command=["exit 7"],
        yoke_home=tmp_path,
        environ=AGENT,
        run=_runner(7, calls),
    )

    assert code == 7
    assert calls[0][-1] == "exit 7"
    assert known_hosts_path(tmp_path).parent.is_dir()


def test_no_ssh_agent_refuses_before_connecting(tmp_path) -> None:
    calls: list[list[str]] = []

    with pytest.raises(RemoteExecRefusal) as refusal:
        run_remote_command(
            host=HOST,
            user=USER,
            command=["true"],
            yoke_home=tmp_path,
            environ={},
            run=_runner(0, calls),
        )

    assert refusal.value.code == "test_machine_ssh_agent_unavailable"
    assert "ssh-add -l" in refusal.value.recovery
    assert calls == []


def test_a_connection_failure_names_the_pinned_key_reset(tmp_path) -> None:
    with pytest.raises(RemoteExecRefusal) as refusal:
        run_remote_command(
            host=HOST,
            user=USER,
            command=["true"],
            yoke_home=tmp_path,
            environ=AGENT,
            run=_runner(255, []),
        )

    assert refusal.value.code == "test_machine_ssh_failed"
    assert (
        f"ssh-keygen -R {HOST} -f {known_hosts_path(tmp_path)}"
        in refusal.value.recovery
    )


def _detail(lease: dict[str, Any] | None) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="test_machine.get",
        version="v1",
        result={
            "machine": "test-mac",
            "settings": {"host": HOST, "user": USER},
            "active_lease": lease,
        },
    )


@pytest.fixture
def cli(monkeypatch, tmp_path):
    ran: list[dict[str, Any]] = []
    monkeypatch.setattr(adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        adapter,
        "build_actor",
        lambda session_id=None: type("Actor", (), {"session_id": "mine"})(),
    )
    monkeypatch.setattr(adapter.machine_config, "yoke_home", lambda: Path(tmp_path))
    monkeypatch.setattr(
        "yoke_harness.test_machine_remote_exec.run_remote_command",
        lambda **kwargs: ran.append(kwargs) or 0,
    )

    def invoke(argv: list[str], *, lease: dict[str, Any] | None = None) -> int:
        monkeypatch.setattr(adapter, "call_dispatcher", lambda **_: _detail(lease))
        return adapter.test_machine_exec(argv)

    invoke.ran = ran  # type: ignore[attr-defined]
    return invoke


def test_the_command_is_routed_as_a_test_machine_subcommand() -> None:
    resolved = resolve_tool_shaped(["test-machine", "exec", "--project", "yoke"])

    assert resolved is not None
    assert resolved[0] is adapter.test_machine_exec


def test_exec_runs_as_the_capability_user_at_its_host(cli) -> None:
    assert cli(["--project", "yoke", "--", "uname", "-a"]) == 0

    assert cli.ran == [
        {
            "host": HOST,
            "user": USER,
            "command": ["uname", "-a"],
            "yoke_home": cli.ran[0]["yoke_home"],
        }
    ]


def test_a_host_leased_by_another_session_is_refused(cli, capsys) -> None:
    lease = {"session_id": "theirs", "item": {"ref": "QA-1"}}

    assert cli(["--project", "yoke", "--", "true"], lease=lease) == 1

    err = capsys.readouterr().err
    assert "test_machine_leased" in err
    assert "session theirs for QA-1" in err
    assert cli.ran == []


def test_the_lease_holder_itself_may_run_commands(cli) -> None:
    assert cli(["--project", "yoke", "--", "true"], lease={"session_id": "mine"}) == 0
    assert len(cli.ran) == 1


def test_a_missing_remote_command_is_a_usage_error(cli, capsys) -> None:
    assert cli(["--project", "yoke"]) == 2
    assert "after `--`" in capsys.readouterr().err
