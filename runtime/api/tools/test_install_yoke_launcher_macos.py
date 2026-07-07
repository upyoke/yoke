"""macOS PATH tests for ``install_yoke_launcher``."""

from __future__ import annotations

import io
from pathlib import Path
from unittest import mock

from yoke_core.tools import install_yoke_launcher as isl


def test_macos_path_fix_skip_reason_non_darwin(monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "linux")
    assert isl._macos_path_fix_skip_reason() == "non-macOS platform"


def test_macos_path_fix_skip_reason_no_brew_bin(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    monkeypatch.setattr(isl, "BREW_APPLE_SILICON_BIN", tmp_path / "does-not-exist")
    reason = isl._macos_path_fix_skip_reason()
    assert reason is not None and "not present" in reason


def test_macos_path_fix_skip_reason_no_paths_file(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    brew = tmp_path / "brew-bin"
    brew.mkdir()
    monkeypatch.setattr(isl, "BREW_APPLE_SILICON_BIN", brew)
    monkeypatch.setattr(isl, "MACOS_PATHS_FILE", tmp_path / "no-such-paths")
    reason = isl._macos_path_fix_skip_reason()
    assert reason is not None and "missing" in reason


def test_macos_path_fix_skip_reason_already_first(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    brew = tmp_path / "opt-homebrew-bin"
    brew.mkdir()
    paths = tmp_path / "paths"
    paths.write_text(f"{brew}\n/usr/local/bin\n/usr/bin\n")
    monkeypatch.setattr(isl, "BREW_APPLE_SILICON_BIN", brew)
    monkeypatch.setattr(isl, "MACOS_PATHS_FILE", paths)
    reason = isl._macos_path_fix_skip_reason()
    assert reason is not None and "already first" in reason


def test_macos_path_fix_skip_reason_needs_fix(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    brew = tmp_path / "opt-homebrew-bin"
    brew.mkdir()
    paths = tmp_path / "paths"
    paths.write_text(f"/usr/local/bin\n/usr/bin\n{brew}\n")
    monkeypatch.setattr(isl, "BREW_APPLE_SILICON_BIN", brew)
    monkeypatch.setattr(isl, "MACOS_PATHS_FILE", paths)
    assert isl._macos_path_fix_skip_reason() is None


def test_configure_macos_path_noop_when_skip_reason_set(monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "linux")
    stream = io.StringIO()
    with mock.patch.object(isl.subprocess, "call") as sp_call, \
         mock.patch.object(isl.subprocess, "run") as sp_run:
        result = isl.configure_macos_path_for_homebrew(stream=stream)
    assert result is False
    assert stream.getvalue() == ""
    sp_call.assert_not_called()
    sp_run.assert_not_called()


def test_configure_macos_path_applies_when_needed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    brew = tmp_path / "opt-homebrew-bin"
    brew.mkdir()
    paths = tmp_path / "paths"
    paths.write_text("/usr/local/bin\n/usr/bin\n/bin\n")
    monkeypatch.setattr(isl, "BREW_APPLE_SILICON_BIN", brew)
    monkeypatch.setattr(isl, "MACOS_PATHS_FILE", paths)

    def fake_call(cmd, *args, **kwargs):
        if len(cmd) >= 3 and cmd[0] == "sudo" and cmd[1] == "cp":
            import shutil as _sh

            _sh.copyfile(cmd[2], cmd[3])
            return 0
        return 0

    def fake_run(cmd, *args, input=None, **kwargs):
        if len(cmd) >= 3 and cmd[0] == "sudo" and cmd[1] == "tee":
            Path(cmd[2]).write_bytes(input or b"")
            return mock.Mock(returncode=0)
        return mock.Mock(returncode=0)

    def fake_check_output(cmd, *args, **kwargs):
        if cmd and cmd[0].endswith("path_helper"):
            return 'PATH="/opt/homebrew/bin:/usr/bin"; export PATH;\n'
        return ""

    def fake_check_call(cmd, *args, **kwargs):
        return 0

    stream = io.StringIO()
    with mock.patch.object(isl.subprocess, "call", side_effect=fake_call), \
         mock.patch.object(isl.subprocess, "run", side_effect=fake_run), \
         mock.patch.object(
             isl.subprocess, "check_output", side_effect=fake_check_output
         ), \
         mock.patch.object(isl.subprocess, "check_call", side_effect=fake_check_call):
        result = isl.configure_macos_path_for_homebrew(stream=stream)

    assert result is True
    new_lines = paths.read_text().splitlines()
    assert new_lines[0] == str(brew)
    assert "/usr/local/bin" in new_lines
    assert "/usr/bin" in new_lines
    out = stream.getvalue()
    assert "macOS PATH fix" in out
    assert "launchctl PATH refreshed" in out or "reboot" in out


def test_configure_macos_path_skips_when_sudo_refused(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    brew = tmp_path / "opt-homebrew-bin"
    brew.mkdir()
    paths = tmp_path / "paths"
    original = "/usr/local/bin\n/usr/bin\n"
    paths.write_text(original)
    monkeypatch.setattr(isl, "BREW_APPLE_SILICON_BIN", brew)
    monkeypatch.setattr(isl, "MACOS_PATHS_FILE", paths)

    stream = io.StringIO()
    with mock.patch.object(isl.subprocess, "call", return_value=1), \
         mock.patch.object(isl.subprocess, "run") as sp_run:
        result = isl.configure_macos_path_for_homebrew(stream=stream)

    assert result is False
    assert paths.read_text() == original
    sp_run.assert_not_called()
    assert "sudo cp failed" in stream.getvalue()
    assert "Apply manually later" in stream.getvalue()
