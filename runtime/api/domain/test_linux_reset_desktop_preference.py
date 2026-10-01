"""Linux home restore retains only the provisioned terminal selection."""

import json
import os
import subprocess
import sys

import pytest

from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM


def operation(home, golden, name):
    return subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, name, str(home), str(golden)],
        input="[]",
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )


@pytest.mark.parametrize("golden_has_preferences", [False, True])
def test_restore_preserves_terminal_selected_after_golden_capture(
    tmp_path, golden_has_preferences
):
    if os.getuid() == 0:
        pytest.skip("archive contract requires a non-root test user")
    home = tmp_path / "home"
    home.mkdir()
    helpers = home / ".config/xfce4/helpers.rc"
    if golden_has_preferences:
        helpers.parent.mkdir(parents=True)
        helpers.write_text("WebBrowser=golden-browser\nTerminalEmulator=old-terminal\n")
    golden = tmp_path / "golden"
    assert operation(home, golden, "capture").returncode == 0
    helpers.parent.mkdir(parents=True, exist_ok=True)
    helpers.write_text("WebBrowser=live-browser\nTerminalEmulator=xfce4-terminal\n")
    (home / "live-only").write_text("discard this")
    result = operation(home, golden, "reset")
    assert result.returncode == 0, result.stdout + result.stderr
    expected = "WebBrowser=golden-browser\n" if golden_has_preferences else ""
    assert helpers.read_text() == expected + "TerminalEmulator=xfce4-terminal\n"
    assert not (home / "live-only").exists()
    assert json.loads(result.stdout)["desktop_terminal_preference_preserved"] is True
    assert helpers.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("symlink_parent", [False, True])
def test_restore_refuses_linked_preference_path_before_clearing(
    tmp_path, symlink_parent
):
    if os.getuid() == 0:
        pytest.skip("archive contract requires a non-root test user")
    home = tmp_path / "home"
    home.mkdir()
    golden = tmp_path / "golden"
    assert operation(home, golden, "capture").returncode == 0
    external = tmp_path / "external"
    external.mkdir()
    helper = external / "helpers.rc"
    helper.write_text("TerminalEmulator=xfce4-terminal\n")
    config = home / ".config"
    config.mkdir()
    if symlink_parent:
        (config / "xfce4").symlink_to(external, target_is_directory=True)
    else:
        (config / "xfce4").mkdir()
        (config / "xfce4/helpers.rc").symlink_to(helper)
    sentinel = home / "sentinel"
    sentinel.write_text("unchanged")
    result = operation(home, golden, "reset")
    assert result.returncode == 64
    assert json.loads(result.stdout)["reason"] == "linux_desktop_preference_unsafe"
    assert sentinel.read_text() == "unchanged"
    assert helper.read_text() == "TerminalEmulator=xfce4-terminal\n"
