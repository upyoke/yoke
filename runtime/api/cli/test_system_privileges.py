"""One OS privilege ladder serves every Linux setup caller."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import system_privileges as authority


@pytest.mark.parametrize(
    "root,sudo,probe_ok,stdin_tty,stderr_tty,prefix,interactive",
    [
        (True, False, False, False, False, [], False),
        (False, True, True, False, False, ["/bin/sudo", "-n", "--"], False),
        (False, True, False, True, True, ["/bin/sudo", "--"], True),
    ],
)
def test_select_first_available_authority(
    monkeypatch,
    root,
    sudo,
    probe_ok,
    stdin_tty,
    stderr_tty,
    prefix,
    interactive,
):
    monkeypatch.setattr(authority.os, "geteuid", lambda: 0 if root else 1000)
    monkeypatch.setattr(
        authority.shutil, "which", lambda name: "/bin/sudo" if sudo else None
    )
    monkeypatch.setattr(
        authority.sys, "stdin", SimpleNamespace(isatty=lambda: stdin_tty)
    )
    monkeypatch.setattr(
        authority.sys, "stderr", SimpleNamespace(isatty=lambda: stderr_tty)
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0 if probe_ok else 1, "", "")

    monkeypatch.setattr(authority.subprocess, "run", run)
    assert authority.command_authority("unavailable: recovery") == (prefix, interactive)
    assert commands == ([] if root else [["/bin/sudo", "-n", "true"]])


@pytest.mark.parametrize(
    "sudo,stdin_tty,stderr_tty",
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
        (True, False, False),
    ],
)
def test_no_authority_preserves_callers_named_reason(
    monkeypatch, sudo, stdin_tty, stderr_tty
):
    monkeypatch.setattr(authority.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        authority.shutil, "which", lambda name: "/bin/sudo" if sudo else None
    )
    monkeypatch.setattr(
        authority.sys, "stdin", SimpleNamespace(isatty=lambda: stdin_tty)
    )
    monkeypatch.setattr(
        authority.sys, "stderr", SimpleNamespace(isatty=lambda: stderr_tty)
    )
    monkeypatch.setattr(
        authority.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(
            command, 1, "", "password needed"
        ),
    )
    with pytest.raises(RuntimeError, match="setup_unavailable: exact recovery"):
        authority.command_authority("setup_unavailable: exact recovery")


def test_unlaunchable_probe_preserves_recovery(monkeypatch):
    monkeypatch.setattr(authority.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(authority.shutil, "which", lambda name: "/missing/sudo")

    def unavailable(command, **kwargs):
        raise FileNotFoundError("sudo disappeared")

    monkeypatch.setattr(authority.subprocess, "run", unavailable)
    with pytest.raises(RuntimeError, match="setup_unavailable: recovery.*probe failed"):
        authority.command_authority("setup_unavailable: recovery")
