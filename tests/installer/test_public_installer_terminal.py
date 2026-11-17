"""Prove the piped shell installer gives setup a safe controlling terminal."""

from __future__ import annotations

import json
import os
import shlex
import signal
import sys
from types import SimpleNamespace

import pytest

from installer_terminal_support import TerminalShell
from public_installer_helpers import (
    FAKE_INSTALL_PY,
    INSTALL_SHIM_PATH,
    write_executable,
    write_uv_stub,
)

pytestmark = pytest.mark.posix_only(reason='POSIX job control')


def assert_restored(output):
    # Readline owns this enable at the returned prompt; setup must still emit
    # its own disable. Job-control cleanup and prompt output can interleave.
    scope = output.replace(b"\x1b[?2004h" + TerminalShell.prompt, TerminalShell.prompt)
    for mode in (1000, 1003, 1004, 1006, 1015, 1016, 2004, 1049):
        enabled, disabled = f"\x1b[?{mode}h".encode(), f"\x1b[?{mode}l".encode()
        if enabled in scope:
            assert scope.rfind(disabled) > scope.rfind(enabled), (mode, output)
    assert b"Traceback" not in output
    assert b"tty input" not in output


@pytest.mark.parametrize("action", ["interrupt", "suspend"])
def test_pipe_install_restores_terminal_on_interrupt_and_suspend(tmp_path, action):
    import termios

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    write_uv_stub(bin_dir, install_py_body=FAKE_INSTALL_PY)
    write_executable(
        bin_dir / "yoke",
        f"#!{sys.executable}\nfrom installer_terminal_support import wizard\nwizard()\n",
    )
    evidence = tmp_path / "terminal.json"
    # Only uv's install/download side effects are stubbed. The real curl,
    # pipe, sh, /dev/tty redirection and setup terminal driver all execute.
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "TERM": "xterm-256color",
        "YOKE_INSTALL_BASE_URL": "https://example.invalid",
        "TERMINAL_EVIDENCE": str(evidence),
        "PYTHONPATH": os.pathsep.join(sys.path),
    }
    shell = TerminalShell(env)
    try:
        shell.wait_for(shell.prompt)
        # Stop readline while comparing cooked terminal attributes; its prompt
        # otherwise deliberately has its own noncanonical input mode.
        baseline = tmp_path / "before"
        restored = tmp_path / "after"
        shell.send(f"stty -g > {shlex.quote(str(baseline))}\n".encode())
        shell.wait_for(shell.prompt, after=len(shell.output))
        start = len(shell.output)
        command = f"curl -fsSL {shlex.quote(INSTALL_SHIM_PATH.as_uri())} | sh\n"
        shell.send(command.encode())
        shell.wait_for(b"PIPE_SETUP_READY", after=start, setup_evidence=evidence)
        terminal = json.loads(evidence.read_text())
        wizard_pid = terminal.pop("pid")
        assert terminal == {
            "stdin_tty": True,
            "foreground": True,
        }
        assert b"\x1b[?1000h" in shell.output[start:]
        if action == "suspend":
            # Textual consumes raw key bytes; job-control suspension arrives
            # as SIGTSTP. Signal the pipeline just as its controlling shell does.
            os.killpg(os.tcgetpgrp(shell.fd), signal.SIGTSTP)
            paused = shell.wait_for(shell.prompt, after=len(shell.output))
            assert b"Stopped" in paused
            shell.wait_stopped(wizard_pid)
            shell.wait_for(b"\x1b[?1004l", after=start)
            assert_restored(bytes(shell.output[start:]))
            resumed = len(shell.output)
            shell.send(b"fg\n")
            shell.wait_for(b"PIPE_SETUP_READY", after=resumed)
            shell.send(b"\x03")
        else:
            shell.send(b"\x03")
        shell.wait_for(shell.prompt, after=len(shell.output))
        assert_restored(bytes(shell.output[start:]))
        # A shell command can read and echo after both cancellation and resume.
        checked = len(shell.output)
        shell.send(
            f"stty -g > {shlex.quote(str(restored))}; printf 'TERMINAL_%s\\n' CLEAN\n".encode()
        )
        shell.wait_for(b"TERMINAL_CLEAN", after=checked)
        shell.wait_for(shell.prompt, after=checked)
        assert termios.tcgetattr(shell.fd)[3] & termios.ISIG
        assert restored.read_text() == baseline.read_text()
    finally:
        shell.close()


@pytest.mark.parametrize("responsive", [True, False])
def test_setup_response_deadline_starts_after_import_evidence(
    tmp_path, monkeypatch, responsive
):
    import installer_terminal_support as support

    evidence = tmp_path / "terminal.json"
    shell = TerminalShell.__new__(TerminalShell)
    shell.fd, shell.pid = 10, 20
    shell.output, shell.job_groups = bytearray(), set()
    shell.process = SimpleNamespace(poll=lambda: None)
    clock = [0]
    monkeypatch.setattr(support.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(support.os, "tcgetpgrp", lambda fd: shell.pid)

    def readable(*args):
        # Model imports taking longer than the terminal response budget without
        # slowing the real terminal tests or relying on the host's import cache.
        clock[0] += 13
        evidence.write_text("{}")
        return [shell.fd], [], []

    chunks = iter([b"imports complete", b"PIPE_SETUP_READY" if responsive else b""])
    monkeypatch.setattr(support.select, "select", readable)
    monkeypatch.setattr(support.os, "read", lambda *args: next(chunks))
    if responsive:
        assert b"PIPE_SETUP_READY" in shell.wait_for(
            b"PIPE_SETUP_READY", setup_evidence=evidence
        )
    else:
        with pytest.raises(AssertionError, match="imports complete"):
            shell.wait_for(b"PIPE_SETUP_READY", setup_evidence=evidence)
