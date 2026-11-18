"""The test-wide browser guard fails a launching test and names it."""

from __future__ import annotations

import subprocess
import webbrowser

import pytest

from runtime.browser_launch_isolation import (
    BrowserLaunchGuard,
    native_browser_launcher,
)

URL = "https://example.invalid/?token=t"


@pytest.mark.parametrize(
    ("args", "launcher"),
    [
        (["open", URL], "open"),
        (["/usr/bin/open", URL], "open"),
        (["/usr/bin/xdg-open", URL], "xdg-open"),
        (["wslview", URL], "wslview"),
        (
            ["/mnt/c/WINDOWS/powershell.exe", "-Command", "Start-Process $env:U"],
            "powershell Start-Process",
        ),
        (["powershell.exe", "-Command", "Get-Date"], None),
        (["cmd", "/c", "start", "", URL], "cmd start"),
        (f"open '{URL}'", "open"),
        (["git", "open"], None),
        (["python3", "-c", "print('open')"], None),
        ([], None),
    ],
)
def test_native_browser_launchers_are_recognised(args, launcher):
    assert native_browser_launcher(args) == launcher


@pytest.fixture()
def guard(tmp_path):
    monkeypatch = pytest.MonkeyPatch()
    installed = BrowserLaunchGuard("suite::test_case", tmp_path / "child")
    installed.install(monkeypatch)
    yield installed
    monkeypatch.undo()


@pytest.mark.parametrize(
    "launch",
    [
        lambda: subprocess.run(["/usr/bin/open", URL], check=False),
        lambda: subprocess.Popen(["xdg-open", URL]),
        lambda: webbrowser.open(URL),
    ],
)
def test_a_real_launch_fails_naming_the_test(guard, launch):
    with pytest.raises(pytest.fail.Exception, match=r"^suite::test_case tried"):
        launch()
    assert guard.verdict().startswith("suite::test_case tried to open a real browser")


def test_a_child_process_browser_fails_at_teardown(guard):
    guard.child_attempt.touch()
    assert "a child process's webbrowser" in guard.verdict()


def test_ordinary_subprocesses_still_run(guard):
    subprocess.run(["true"], check=True)
    assert guard.verdict() is None


@pytest.mark.posix_only(
    reason="fake launcher is a #!/bin/sh script; Windows CreateProcess refuses it"
)
def test_a_fake_launcher_under_tmp_path_is_allowed(guard, tmp_path):
    fake = tmp_path / "powershell.exe"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    subprocess.run([str(fake), "-Command", "Start-Process $env:U"], check=True)
    assert guard.verdict() is None
