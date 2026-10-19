"""Linux reset ends the desktop first and keeps live sign-ins through a failed clear."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM


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


def execute_reset(monkeypatch, home, golden, program=_ARCHIVE_PROGRAM):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "python",
            "reset",
            str(home),
            str(golden),
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


@pytest.mark.parametrize("stop_fails", [False, True])
def test_reset_ends_open_desktop_before_clearing_home(
    archive_home, monkeypatch, capsys, stop_fails
):
    from yoke_harness.ssh_linux_reset_preconditions import DESKTOP_PROGRAM

    home, golden, credential = archive_home
    sentinel = home / "sentinel"
    sentinel.write_text("live")
    replacement = """
import subprocess
def stop_desktop():
    assert (home / "sentinel").read_text() == "live"
    (home.parent / "desktop-stopped").write_text("proved")
"""
    if stop_fails:
        replacement += '    raise RuntimeError("termination unavailable")\n'
    program = _ARCHIVE_PROGRAM.replace(DESKTOP_PROGRAM, replacement)
    if stop_fails:
        with pytest.raises(SystemExit):
            execute_reset(monkeypatch, home, golden, program=program)
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["reason"] == "linux_desktop_stop_not_proved"
        assert "termination unavailable" in receipt["recovery"]
        assert sentinel.read_text() == "live"
    else:
        execute_reset(monkeypatch, home, golden, program=program)
        assert json.loads(capsys.readouterr().out)["ok"]
        assert not sentinel.exists()
    assert (home.parent / "desktop-stopped").read_text() == "proved"
    assert credential.read_bytes() == b"opaque-live-new-after-refresh"


def test_symlinked_live_credential_refuses_before_teardown(
    archive_home, monkeypatch, capsys
):
    home, golden, credential = archive_home
    outside = home.parent / "outside"
    credential.rename(outside)
    credential.symlink_to(outside)
    with pytest.raises(SystemExit) as refused:
        execute_reset(monkeypatch, home, golden)
    assert refused.value.code == 64
    assert (
        json.loads(capsys.readouterr().out)["reason"]
        == "linux_preserved_home_entry_unsafe"
    )
    assert (home / "settings").read_text() == "live"
    assert credential.read_bytes() == b"opaque-live-new-after-refresh"
