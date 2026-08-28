"""Operator-set machine name the relay reports as hostname."""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

from yoke_contracts.machine_config import machine_name as machine_name_module


# The bounded PATH launchd hands the relay daemon. /usr/sbin, where scutil
# lives, is absent from it, which is the environment this module must answer
# correctly in — and the only environment that persists the answer.
DAEMON_PATH_WITHOUT_USR_SBIN = "/bin:/usr/bin"


@pytest.fixture(autouse=True)
def _forget_reported_failures() -> None:
    machine_name_module._reported_probe_failures.clear()


def _local_host_name() -> str:
    """Return this Mac's operator-set name, resolved outside the module."""
    completed = subprocess.run(
        ("/usr/sbin/scutil", "--get", "LocalHostName"),
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def test_every_probe_command_is_an_absolute_path() -> None:
    # A bare name resolves through the caller's PATH, which is how this
    # resolution passed from a terminal while the relay daemon reported "Mac".
    commands = (
        machine_name_module.DARWIN_PROBE_COMMANDS
        + machine_name_module.LINUX_PROBE_COMMANDS
    )

    assert commands
    for command in commands:
        assert command[0].startswith("/"), command


@pytest.mark.skipif(sys.platform != "darwin", reason="scutil is macOS-only")
def test_the_operator_set_name_resolves_without_usr_sbin_on_path(monkeypatch) -> None:
    # The regression itself: same interpreter, same module, only PATH differs.
    operator_set = _local_host_name()
    if not operator_set:
        pytest.skip("this Mac has no LocalHostName set")
    monkeypatch.setenv("PATH", DAEMON_PATH_WITHOUT_USR_SBIN)

    assert machine_name_module.machine_display_name() == operator_set


def test_darwin_prefers_local_host_name_over_the_kernel_host(monkeypatch) -> None:
    monkeypatch.setattr(machine_name_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        machine_name_module,
        "_probe",
        lambda command: machine_name_module._ProbeOutcome(
            name=(
                "beebauman-macbook-pro-16"
                if command == machine_name_module.DARWIN_PROBE_COMMANDS[0]
                else "ignored-computer-name"
            )
        ),
    )
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "Mac")

    assert machine_name_module.machine_display_name() == "beebauman-macbook-pro-16"


def test_darwin_falls_back_to_computer_name_when_local_host_name_is_unset(
    monkeypatch,
) -> None:
    monkeypatch.setattr(machine_name_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        machine_name_module,
        "_probe",
        lambda command: machine_name_module._ProbeOutcome(
            name=(
                "Bee MacBook"
                if command == machine_name_module.DARWIN_PROBE_COMMANDS[1]
                else ""
            )
        ),
    )
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "Mac")

    assert machine_name_module.machine_display_name() == "Bee MacBook"


def test_machine_name_falls_back_to_the_host_name_when_unset(monkeypatch) -> None:
    # The systemd pretty hostname is routinely unset, and an unset value is an
    # answer rather than a failure.
    monkeypatch.setattr(machine_name_module.sys, "platform", "linux")
    monkeypatch.setattr(
        machine_name_module,
        "_probe",
        lambda _command: machine_name_module._ProbeOutcome(),
    )
    monkeypatch.setattr(
        machine_name_module.socket, "gethostname", lambda: "build-runner-3"
    )

    assert machine_name_module.machine_display_name() == "build-runner-3"


def test_an_unrunnable_probe_still_leaves_a_usable_name(monkeypatch) -> None:
    def absent(_command, **_kwargs):
        raise FileNotFoundError("scutil")

    monkeypatch.setattr(machine_name_module.subprocess, "run", absent)
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "fallback")

    assert machine_name_module.machine_display_name() == "fallback"


def test_an_unrunnable_probe_is_reported_as_a_named_failure(
    monkeypatch, caplog
) -> None:
    # Folding "could not run" into the ordinary fallback is what hid this
    # defect through several rounds of fixing it.
    monkeypatch.setattr(machine_name_module.sys, "platform", "darwin")

    def absent(_command, **_kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(machine_name_module.subprocess, "run", absent)
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "Mac")

    with caplog.at_level(logging.WARNING, logger=machine_name_module.__name__):
        assert machine_name_module.machine_display_name() == "Mac"

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "/usr/sbin/scutil could not be executed" in message
    assert "confirm the path exists and is executable" in message


def test_a_probe_that_declines_to_answer_is_not_reported_as_a_failure(
    monkeypatch, caplog
) -> None:
    # A non-zero exit means the platform holds no operator-set name, which is
    # an ordinary reason to use the host name.
    monkeypatch.setattr(machine_name_module.sys, "platform", "linux")
    monkeypatch.setattr(
        machine_name_module.subprocess,
        "run",
        lambda _command, **_kwargs: subprocess.CompletedProcess(
            _command, 1, stdout="", stderr="not set"
        ),
    )
    monkeypatch.setattr(
        machine_name_module.socket, "gethostname", lambda: "build-runner-3"
    )

    with caplog.at_level(logging.WARNING, logger=machine_name_module.__name__):
        assert machine_name_module.machine_display_name() == "build-runner-3"

    assert caplog.records == []


def test_a_repeated_unrunnable_probe_is_reported_once_per_process(
    monkeypatch, caplog
) -> None:
    # The relay re-resolves the name on every heartbeat; a warning per beat
    # would bury the rest of its log.
    monkeypatch.setattr(machine_name_module.sys, "platform", "darwin")

    def absent(_command, **_kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(machine_name_module.subprocess, "run", absent)
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "Mac")

    with caplog.at_level(logging.WARNING, logger=machine_name_module.__name__):
        machine_name_module.machine_display_name()
        machine_name_module.machine_display_name()

    assert len(caplog.records) == 1
