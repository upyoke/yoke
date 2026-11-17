"""Portable stream tests plus real PowerShell/cmd output capture on Windows CI."""

from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from yoke_cli.config import native_windows_terminal as terminal


pytestmark = pytest.mark.windows


def test_non_utf8_streams_become_utf8_without_color(monkeypatch):
    buffers = (io.BytesIO(), io.BytesIO())
    streams = tuple(
        io.TextIOWrapper(buffer, encoding="cp1252", newline="\n") for buffer in buffers
    )
    monkeypatch.setattr(
        terminal,
        "sys",
        SimpleNamespace(platform="win32", stdout=streams[0], stderr=streams[1]),
    )
    env = {}
    monkeypatch.setattr(terminal, "os", SimpleNamespace(environ=env))
    terminal.configure()
    for stream in streams:
        stream.write("José 東京 ✓\n")
        stream.flush()
    assert all(
        buffer.getvalue().decode("utf-8") == "José 東京 ✓\n" for buffer in buffers
    )
    assert env["NO_COLOR"] == "1"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_os_streams_and_color_unchanged(monkeypatch, platform):
    stream = SimpleNamespace(reconfigure=lambda **kw: pytest.fail("not Windows"))
    monkeypatch.setattr(
        terminal,
        "sys",
        SimpleNamespace(platform=platform, stdout=stream, stderr=stream),
    )
    monkeypatch.delenv("NO_COLOR", raising=False)
    terminal.configure()
    assert "NO_COLOR" not in os.environ


@pytest.mark.parametrize("setting,value", [("NO_COLOR", "1"), ("TERM", "dumb")])
def test_explicit_no_color_console(monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    assert not terminal.supports_color(SimpleNamespace(isatty=lambda: True))


@pytest.mark.windows_only(reason='real native Windows shell captures')
@pytest.mark.parametrize("shell", ["cmd.exe", "powershell.exe", "pwsh.exe"])
@pytest.mark.parametrize("surface", ["status", "setup"])
def test_native_shell_output_capture(tmp_path, shell, surface, request):
    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f"{shell} is not installed on this Windows runner")
    script = tmp_path / "capture.py"
    started_marker = tmp_path / "python-started.txt"
    shell_marker = tmp_path / "shell-started.txt"
    common = (
        "import pathlib, time; "
        f"pathlib.Path({str(started_marker)!r}).write_text(str(time.time())); "
        "import sys; sys.stdout.reconfigure(encoding='cp1252', errors='strict'); "
    )
    if surface == "status":
        code = (
            "from yoke_cli.commands.adapters import config; "
            "config.machine_config_status.build_status=lambda **kw: "
            "dict(ok=True, config_path='José 東京', repo_root='C:/src', issues=[]); "
            "config._status([], prog='capture', usage='capture')"
        )
    else:
        code = (
            "from yoke_cli.commands.adapters import onboard; "
            "onboard.parse_or_usage_error=lambda *a: print('José 東京 ✓'); "
            "onboard.onboard([])"
        )
    script.write_text(common + code, encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "NO_COLOR": "1"}
    if shell == "cmd.exe":
        command = "chcp 65001 >nul & " + subprocess.list2cmdline(
            [sys.executable, str(script)]
        )
        argv = [executable, "/d", "/s", "/c", command]
    else:

        def quote(text):
            return "'" + text.replace("'", "''") + "'"

        command = (
            "[IO.File]::WriteAllText("
            + quote(str(shell_marker))
            + ", [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString()); "
            + "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); & "
            + quote(sys.executable)
            + " "
            + quote(str(script))
            + "; exit $LASTEXITCODE"
        )
        argv = [executable, "-NoProfile", "-NonInteractive", "-Command", command]
    launched_at = time.time()
    try:
        result = subprocess.run(
            argv, capture_output=True, stdin=subprocess.DEVNULL, env=env, timeout=30
        )
    except subprocess.TimeoutExpired as exc:
        request.node.user_properties.append(("python_started", started_marker.exists()))
        if started_marker.exists():
            startup_seconds = float(started_marker.read_text()) - launched_at
            diagnostic = (
                f"Python started after {startup_seconds:.3f}s; "
                "output capture did not finish within 30s"
            )
        else:
            diagnostic = "Python never started within 30s"
        if shell != "cmd.exe":
            if shell_marker.exists():
                shell_seconds = float(shell_marker.read_text()) / 1000 - launched_at
                diagnostic += f"; PowerShell command started after {shell_seconds:.3f}s"
            else:
                diagnostic += "; PowerShell command never started within 30s"
        pytest.fail(
            f"{shell} / {surface}: {diagnostic}; "
            f"stdout={exc.stdout!r}; stderr={exc.stderr!r}",
            pytrace=False,
        )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    startup_seconds = float(started_marker.read_text()) - launched_at
    request.node.user_properties.append(("python_startup_seconds", startup_seconds))
    if shell_marker.exists():
        shell_seconds = float(shell_marker.read_text()) / 1000 - launched_at
        request.node.user_properties.append(("shell_startup_seconds", shell_seconds))
    print(f"WINDOWS_SHELL_START {shell} {surface}: {startup_seconds:.3f}s")
    output = result.stdout.decode("utf-8-sig")
    assert "José 東京" in output and "\x1b[" not in output
    print(f"WINDOWS_SHELL_CAPTURE {shell} {surface}: {output.strip()}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open(
            "a", encoding="utf-8"
        ) as summary:
            summary.write(
                f"\n### Native shell capture: {shell} / {surface}\n```text\n"
                + output.strip()
                + "\n```\nUTF-8 decoded successfully; no ANSI color escapes.\n"
            )
