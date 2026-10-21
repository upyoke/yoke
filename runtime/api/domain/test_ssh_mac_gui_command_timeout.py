"""A GUI-session command that times out is stopped and returns what it printed."""

from __future__ import annotations

import base64
import subprocess

import pytest

from yoke_core.domain.agent_mission_host_command_cli import approval_wait_warning
from yoke_harness.ssh_mac_gui_session import (
    GUI_COMMAND_TIMEOUT_EXIT_CODE,
    GUI_COMMAND_TIMEOUT_NOT_STOPPED,
    GUI_COMMAND_TIMEOUT_STOPPED,
    GUI_COMMAND_WINDOW_NOT_CLOSED,
    run_terminal_app_command,
)
from yoke_harness.ssh_mac_process_tree import stop_process_tree


def _done(command: str, returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class GuiHost:
    """A host whose command never finishes unless told it does."""

    def __init__(
        self,
        *,
        finishes: bool = False,
        pid: str | None = "4242",
        stop: tuple[int, str] = (0, ""),
        closes: bool = True,
        printed: tuple[str, str] = ("out", "out"),
    ) -> None:
        self.finishes, self.pid, self.stop, self.closes = finishes, pid, stop, closes
        self.printed = dict(zip((".stdout", ".stderr"), printed))
        self.commands: list[str] = []

    def __call__(self, command: str, **_kwargs) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if "set targetTab to do script" in command:
            return _done(command, stdout="441\n")
        if command.startswith("if /bin/test -f "):
            return _done(command, stdout="0\n") if self.finishes else _done(command, 1)
        if command.startswith("/usr/bin/base64 < "):
            if command.endswith(".pid") or command.endswith(".pid'"):
                if self.pid is None:
                    return _done(command, 1)
                return _done(
                    command, stdout=base64.b64encode(self.pid.encode()).decode()
                )
            text = next(v for k, v in self.printed.items() if k in command)
            return _done(command, stdout=base64.b64encode(text.encode()).decode())
        if command.startswith("/bin/sh -c 'process_tree()"):
            return _done(command, self.stop[0], stdout=self.stop[1])
        if "set ttyPaths to tty of every tab" in command:
            return _done(command, stdout="closed\n" if self.closes else "open\n")
        return _done(command)

    def removed(self) -> list[str]:
        return [c for c in self.commands if c.startswith("/bin/rm -f ")]


def _run(host: GuiHost) -> subprocess.CompletedProcess:
    return run_terminal_app_command(host, argv=("/usr/bin/true",), timeout=1)


def test_the_command_records_its_pid_and_execs_in_place() -> None:
    host = GuiHost(finishes=True)

    result = _run(host)

    assert result.returncode == 0
    launch = next(c for c in host.commands if "set targetTab to do script" in c)
    assert "/bin/sh -c" in launch and "exec" in launch and ".pid" in launch
    assert ".pid" in host.removed()[0]


def test_a_timed_out_command_is_stopped_before_its_output_is_removed() -> None:
    host = GuiHost()

    result = _run(host)

    assert result.returncode == GUI_COMMAND_TIMEOUT_EXIT_CODE
    assert result.stderr.splitlines()[-1].startswith(GUI_COMMAND_TIMEOUT_STOPPED)
    assert "pid 4242" in result.stderr
    stop = next(
        i
        for i, c in enumerate(host.commands)
        if c.startswith("/bin/sh -c 'process_tree()")
    )
    assert "process_tree 4242" in host.commands[stop]
    remove = host.commands.index(host.removed()[0])
    close = next(i for i, c in enumerate(host.commands) if "set ttyPaths to tty" in c)
    # The wrapper shell dies with the window before the files go, so it cannot
    # write the stopped command's exit status after the cleanup.
    assert stop < close < remove


@pytest.mark.parametrize("stop", [(0, ""), (1, "4242\n")])
def test_a_timed_out_command_returns_what_it_printed_before_the_deadline(
    stop: tuple[int, str],
) -> None:
    # A command that prints its approval line, then waits past the timeout.
    host = GuiHost(stop=stop, printed=('{"approve_url": "https://x"}\n', "waiting\n"))

    result = _run(host)

    assert result.returncode == GUI_COMMAND_TIMEOUT_EXIT_CODE
    assert result.stdout == '{"approve_url": "https://x"}\n'
    assert result.stderr.splitlines()[0] == "waiting"
    assert "did not finish within 1s" in result.stderr.splitlines()[-1]


def test_a_silent_timed_out_command_returns_only_the_timeout_message() -> None:
    result = _run(GuiHost(printed=("", "")))

    assert result.stdout == ""
    assert result.stderr.startswith(GUI_COMMAND_TIMEOUT_STOPPED)


@pytest.mark.parametrize(
    ("host", "named"),
    [
        (GuiHost(stop=(1, "4242 4250\n")), "processes 4242 4250 survived"),
        (GuiHost(pid=None), "never recorded its pid"),
        (GuiHost(stop=(255, "")), "exit 255"),
    ],
)
def test_an_unconfirmed_stop_keeps_the_output_and_names_its_paths(
    host: GuiHost, named: str
) -> None:
    result = _run(host)

    assert result.returncode == GUI_COMMAND_TIMEOUT_EXIT_CODE
    assert result.stderr.splitlines()[-1].startswith(GUI_COMMAND_TIMEOUT_NOT_STOPPED)
    assert named in result.stderr
    assert ".stdout" in result.stderr and ".pid" in result.stderr
    assert host.removed() == []


def test_a_window_left_open_is_named_beside_the_commands_answer() -> None:
    result = _run(GuiHost(finishes=True, closes=False))

    assert result.returncode == 0
    assert result.stdout == "out"
    assert result.stderr.splitlines()[-1].startswith(GUI_COMMAND_WINDOW_NOT_CLOSED)
    assert "yoke test-machine reset" in result.stderr


@pytest.mark.parametrize(
    ("returncode", "stdout", "stopped", "survivors"),
    [(0, "", True, ()), (1, "12 13\n", False, (12, 13)), (2, "", False, ())],
)
def test_process_tree_stop_reports_what_survived(
    returncode, stdout, stopped, survivors
) -> None:
    commands: list[str] = []

    def run(command: str, **_kwargs):
        commands.append(command)
        return _done(command, returncode, stdout)

    stop = stop_process_tree(run, 77)

    assert (stop.stopped, stop.survivors) == (stopped, survivors)
    assert commands[0].startswith("/bin/sh -c ")
    assert "process_tree 77" in commands[0]
    assert commands[0].index("stop TERM") < commands[0].index("stop KILL")


@pytest.mark.parametrize(
    ("command", "timeout", "warned"),
    [
        (["yoke", "setup"], 60, True),
        (["/Users/t/.local/bin/yoke", "connect"], 599, True),
        (["{yoke_bin}", "onboard"], 60, True),
        (["yoke", "setup"], 600, False),
        (["yoke", "setup", "--agent"], 60, False),
        (["yoke", "setup", "--answer", "connect.saved_destination=stored"], 240, False),
        (["yoke", "setup", "--answer=connect.saved_destination=stored"], 240, False),
        (["yoke", "status"], 60, False),
        (["claude", "-p", "setup"], 60, False),
    ],
)
def test_host_command_warns_when_it_would_cut_an_approval_wait_short(
    command: list[str], timeout: int, warned: bool
) -> None:
    warning = approval_wait_warning(command, timeout)

    assert (warning is not None) is warned
    if warned:
        assert "host_command_timeout_below_approval_wait" in warning
        assert "--timeout-seconds 600" in warning
