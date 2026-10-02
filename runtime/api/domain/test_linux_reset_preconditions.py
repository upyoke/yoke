"""Linux reset refuses before mutation and never rolls back live Claude OAuth."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM, archive_operation
from yoke_harness.ssh_linux_reset_preconditions import DESKTOP_PROGRAM, reset_preflight


def probes(program="claude"):
    return json.dumps(
        {"probes": [{"name": "authenticated", "argv": [f"/usr/bin/{program}"]}]}
    )


def control(document, result=None):
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        if isinstance(result, Exception):
            raise result
        return result

    return SimpleNamespace(
        home="/home/tester",
        calls=calls,
        _run=lambda *a, **kw: subprocess.CompletedProcess(a, 0, '{"ok":true}', ""),
        read_remote_text=lambda _: document,
        run_command=request,
    )


@pytest.mark.parametrize(
    "document", [probes("codex"), probes("cursor-agent"), probes("true")]
)
def test_claude_not_declared_does_not_probe_or_preserve(document):
    host = control(document)
    result = reset_preflight(host, "/golden")
    assert result.ok and not result.evidence["preserve_claude"]
    assert host.calls == []


@pytest.mark.parametrize(
    "error,cause",
    [
        ("OAuth session expired and could not be refreshed", "auth"),
        ("Network error: fetch failed", "network"),
        ("Workspace Trust Required", "request"),
        (subprocess.TimeoutExpired("claude", 120), "timeout"),
    ],
)
def test_failed_live_request_blocks_archive_and_teaches_specific_recovery(error, cause):
    host = control(
        probes(),
        error
        if isinstance(error, Exception)
        else subprocess.CompletedProcess([], 1, "", error),
    )
    result = archive_operation(host, "reset", "/golden")
    assert not result.ok and result.error_code == f"linux_reset_claude_{cause}_failed"
    assert ("sign in again" in result.evidence["recovery"]) == (cause == "auth")
    if cause in {"auth", "network"}:
        assert result.evidence["reason"] == error


def test_live_request_uses_native_tool_free_adapter_before_restore():
    host = control(
        probes(),
        subprocess.CompletedProcess(
            [], 0, '{"type":"result","subtype":"success","result":"OK"}', ""
        ),
    )
    result = reset_preflight(host, "/golden")
    assert result.ok and result.evidence["preserve_claude"]
    argv = host.calls[0][0]
    assert "--safe-mode" in argv and "--strict-mcp-config" in argv
    assert argv[argv.index("--tools") + 1] == ""


@pytest.fixture
def archive_home(tmp_path):
    if os.getuid() == 0:
        pytest.skip("archive requires the non-root test user")
    home = tmp_path / "home"
    credential = home / ".claude/.credentials.json"
    credential.parent.mkdir(parents=True)
    credential.write_bytes(b"opaque-golden-old")
    credential.chmod(0o600)
    (home / "settings").write_text("golden")
    golden = tmp_path / "golden"
    result = subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, "capture", str(home), str(golden)],
        input="[]",
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    credential.write_bytes(b"opaque-live-new-after-refresh")
    (home / "settings").write_text("live")
    return home, golden, credential


def execute_reset(monkeypatch, home, golden, program=_ARCHIVE_PROGRAM, preserve=True):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "python",
            "reset",
            str(home),
            str(golden),
            "preserve-claude" if preserve else "golden-credentials",
        ],
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    exec(program, {})


@pytest.mark.parametrize("midway", [False, True])
def test_live_credential_survives_success_and_midway_failure(
    archive_home, monkeypatch, capsys, midway
):
    home, golden, credential = archive_home
    (home / "thinclient_drives").mkdir()  # logout leaves an empty unmounted directory
    stashes = []
    import tempfile

    original = tempfile.mkdtemp

    def private_stash(*args, **kwargs):
        path = original(*args, **kwargs)
        stashes.append(Path(path))
        assert Path(path).stat().st_mode & 0o777 == 0o700
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", private_stash)
    if midway:
        original_clear = shutil.rmtree

        def fail_after_credential_clear(path, *a, **kw):
            if Path(path) == home / "thinclient_drives":
                raise OSError("mounted after admission")
            return original_clear(path, *a, **kw)

        monkeypatch.setattr(shutil, "rmtree", fail_after_credential_clear)
        with pytest.raises(SystemExit) as refused:
            execute_reset(monkeypatch, home, golden)
        assert refused.value.code == 64
        assert (
            json.loads(capsys.readouterr().out)["reason"]
            == "linux_golden_home_clear_failed"
        )
    else:
        # Two consecutive restores keep the live bytes, settings remain golden.
        execute_reset(monkeypatch, home, golden)
        execute_reset(monkeypatch, home, golden)
        receipts = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert all(
            ".claude/.credentials.json" in row["preserved_entries"] for row in receipts
        )
        assert (home / "settings").read_text() == "golden"
        assert not (home / "thinclient_drives").exists()
    assert credential.read_bytes() == b"opaque-live-new-after-refresh"
    assert credential.stat().st_uid == os.getuid()
    assert credential.stat().st_mode & 0o777 == 0o600
    assert stashes and all(not path.exists() for path in stashes)


@pytest.mark.parametrize("desktop", ["mounted", "xfce", "graphical"])
def test_desktop_refusal_leaves_home_bytes_and_running_process_untouched(
    archive_home, tmp_path, monkeypatch, capsys, desktop
):
    home, golden, credential = archive_home
    sentinel = home / "sentinel"
    sentinel.write_bytes(b"untouched")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", str(home)]
    )
    signals = []
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self/mountinfo").write_text("")
    if desktop == "xfce":
        (proc / "42").mkdir()
        (proc / "42/comm").write_text("xfce4-session\n")
    real_path = Path

    def path(value):
        if str(value) == "/proc":
            return proc
        if str(value) == "/run/systemd/system" and desktop == "graphical":
            return proc
        return real_path(value)

    real_run = subprocess.run

    def run(argv, **kwargs):
        if argv[0] == "loginctl":
            output = (
                f"c1 {os.getuid()} tester seat0 tty1\n"
                if "list-sessions" in argv
                else "Type=wayland\nActive=yes\n"
            )
            return subprocess.CompletedProcess(argv, 0, output, "")
        return real_run(argv, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                shutil,
                "which",
                lambda _: "loginctl" if desktop == "graphical" else None,
            )
            patch.setattr(subprocess, "run", run)
            patch.setattr(os.path, "ismount", lambda _: desktop == "mounted")
            patch.setattr(os, "kill", lambda *a: signals.append(a))
            patch.setattr(sys.modules["pathlib"], "Path", path)
            with pytest.raises(SystemExit) as stopped:
                execute_reset(
                    patch,
                    home,
                    golden,
                    program=_ARCHIVE_PROGRAM.replace(
                        "            # STOP_YOKE_WRITERS",
                        "            os.kill(123, 15)",
                    ),
                )
            assert stopped.value.code == 64
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["reason"] == "linux_reset_desktop_logged_in"
        assert (
            receipt["recovery"] == "operator is logged in to the desktop; log out first"
        )
        assert credential.read_bytes() == b"opaque-live-new-after-refresh"
        assert sentinel.read_bytes() == b"untouched"
        assert not signals and child.poll() is None
    finally:
        child.terminate()
        child.wait()


def test_dead_login_admission_does_not_clear_home_or_stop_processes(
    archive_home, monkeypatch
):
    home, golden, credential = archive_home
    host = control(
        probes(),
        subprocess.CompletedProcess(
            [], 1, "", "OAuth session expired and could not be refreshed"
        ),
    )
    host.home = str(home)
    commands = []
    host._run = lambda *a, **kw: (
        commands.append(a[0]) or subprocess.CompletedProcess([], 0, '{"ok":true}', "")
    )
    before = {
        str(path.relative_to(home)): path.read_bytes()
        for path in home.rglob("*")
        if path.is_file()
    }
    signals = []
    monkeypatch.setattr(os, "kill", lambda *a: signals.append(a))
    result = archive_operation(host, "reset", str(golden))
    assert not result.ok and len(commands) == 1
    assert DESKTOP_PROGRAM in commands[0] and "archive.extractall" not in commands[0]
    assert not signals
    assert before == {
        str(path.relative_to(home)): path.read_bytes()
        for path in home.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("unsafe", ["symlink", "permissions"])
def test_unsafe_live_credential_refuses_before_teardown(
    archive_home, monkeypatch, capsys, unsafe
):
    home, golden, credential = archive_home
    if unsafe == "symlink":
        outside = home.parent / "outside"
        credential.rename(outside)
        credential.symlink_to(outside)
    else:
        credential.chmod(0o644)
    with pytest.raises(SystemExit) as refused:
        execute_reset(monkeypatch, home, golden)
    assert refused.value.code == 64
    assert (
        json.loads(capsys.readouterr().out)["reason"]
        == "linux_claude_credentials_unsafe"
    )
    assert (home / "settings").read_text() == "live"
    assert credential.read_bytes() == b"opaque-live-new-after-refresh"
